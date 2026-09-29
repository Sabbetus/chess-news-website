// Rehype plugin: links the first mention of a profiled player (up to
// MAX_PLAYERS per article) and of one major event to their pages on this
// site. Runs at build time over every article, so old pieces get links too
// and the drafting pipeline needs no change.
//
// Rules: full names and listed aliases only (a bare surname collides --
// Javokhir vs Komil Sindarov); each player or event linked at most once;
// never inside headings, quotes, code or an existing link; only published
// player/event pages; article files only (profiles don't link to
// themselves).
import { readdirSync, readFileSync } from 'node:fs';

const MAX_PLAYERS = 3;
const MAX_EVENTS = 1;
const SKIP = new Set(['a', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'blockquote', 'code', 'pre', 'figcaption']);

function loadEntities(dir, base) {
  const url = new URL(dir, import.meta.url);
  const out = [];
  for (const name of readdirSync(url)) {
    if (!name.endsWith('.md')) continue;
    const text = readFileSync(new URL(name, url), 'utf-8');
    const fm = text.split('---')[1] ?? '';
    if (!/^reviewStatus:\s*"published"/m.test(fm)) continue;
    const main = fm.match(/^name:\s*"(.*)"\s*$/m)?.[1];
    const block = fm.match(/^aliases:\n((?:\s+- .*\n)+)/m)?.[1] ?? '';
    const aliases = [...block.matchAll(/- "(.*)"/g)].map((m) => m[1]);
    const names = [...new Set([main, ...aliases].filter(Boolean))];
    out.push({ href: `${base}${name.replace(/\.md$/, '')}/`, names });
  }
  return out;
}

// A match that's really part of a different event's name is skipped:
// "Chess Olympiad for People with Disabilities", "Online Chess Olympiad",
// "World Junior Championship".
const NOT_BEFORE = /(?:Online|Junior|Youth|Senior|Disability|Disabilities|Amateur|Schools?|U\d+)\s+$/i;
const NOT_AFTER = /^\s+(?:for\s+People|for\s+the\s+Disabled|Juniors?\b)/i;

const escape = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/'/g, "['’]");

function buildMatcher(entities) {
  const byName = new Map();
  for (const e of entities) for (const n of e.names) byName.set(n.replace(/’/g, "'"), e);
  // Longest first, so "Women's Candidates Tournament" beats "Candidates Tournament".
  const names = [...byName.keys()].sort((a, b) => b.length - a.length);
  if (names.length === 0) return null;
  return {
    re: new RegExp(`(?<![\\p{L}\\p{N}])(?:${names.map(escape).join('|')})(?![\\p{L}\\p{N}])`, 'gu'),
    lookup: (text) => byName.get(text.replace(/’/g, "'")),
  };
}

export default function linkHubs() {
  const players = buildMatcher(loadEntities('../src/content/players/', '/players/'));
  const events = buildMatcher(loadEntities('../src/content/events/', '/events/'));

  return (tree, file) => {
    const path = file?.path ?? file?.history?.[0] ?? '';
    if (!path.includes('/content/articles/')) return;
    const used = new Set();
    const counts = { player: 0, event: 0 };
    // Links the article already has to our own pages count as used.
    (function collect(node) {
      if (node.tagName === 'a' && typeof node.properties?.href === 'string') used.add(node.properties.href);
      (node.children ?? []).forEach(collect);
    })(tree);

    function nextMatch(text) {
      let best = null;
      for (const [kind, m, cap] of [['player', players, MAX_PLAYERS], ['event', events, MAX_EVENTS]]) {
        if (!m || counts[kind] >= cap) continue;
        m.re.lastIndex = 0;
        for (const hit of text.matchAll(m.re)) {
          const entity = m.lookup(hit[0]);
          if (!entity || used.has(entity.href)) continue;
          if (kind === 'event' && (NOT_BEFORE.test(text.slice(0, hit.index)) || NOT_AFTER.test(text.slice(hit.index + hit[0].length)))) continue;
          if (!best || hit.index < best.index || (hit.index === best.index && hit[0].length > best.text.length)) {
            best = { index: hit.index, text: hit[0], entity, kind };
          }
          break;
        }
      }
      return best;
    }

    function walk(node) {
      if (!node.children) return;
      const out = [];
      for (const child of node.children) {
        if (child.type === 'element') {
          if (!SKIP.has(child.tagName)) walk(child);
          out.push(child);
          continue;
        }
        if (child.type !== 'text') {
          out.push(child);
          continue;
        }
        let rest = child.value;
        let hit;
        while (rest && (hit = nextMatch(rest))) {
          if (hit.index > 0) out.push({ type: 'text', value: rest.slice(0, hit.index) });
          out.push({
            type: 'element',
            tagName: 'a',
            properties: { href: hit.entity.href, className: ['hub-link'] },
            children: [{ type: 'text', value: hit.text }],
          });
          used.add(hit.entity.href);
          counts[hit.kind] += 1;
          rest = rest.slice(hit.index + hit.text.length);
        }
        if (rest) out.push({ type: 'text', value: rest });
      }
      node.children = out;
    }
    walk(tree);
  };
}
