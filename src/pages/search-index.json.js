import { getCollection } from 'astro:content';
import { excerptFrom } from '../lib/excerpt';
import { sourceNames } from '../lib/sources';
import { eventPages, playerPages, federationName } from '../lib/hubs';
import { publishedAt } from '../lib/publishedAt';

// A small, static search index built at deploy time -- there's no backend
// to query, so the client fetches this once and filters it locally. Kept
// light: no article bodies. Instead each article carries the names of the
// player and event pages it mentions ("tags"), so "gukesh sindarov" finds
// the pieces about them even when the headline uses only surnames, and
// player and event pages are results of their own (kind "p" and "e").
// Fields: k kind, t title, u path, m meta line, x extra searchable text.
const esc = (a) => a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
const matcher = (aliases) => new RegExp(`(?<![\\p{L}])(?:${aliases.map(esc).join('|')})(?![\\p{L}])`, 'u');

export async function GET() {
  const articles = (await getCollection('articles', ({ data }) => data.reviewStatus === 'published')).sort(
    (a, b) => publishedAt(b).valueOf() - publishedAt(a).valueOf()
  );
  const players = await playerPages();
  const events = await eventPages();

  const hubs = [
    ...players.map((p) => ({ name: p.data.name, re: matcher([p.data.name, ...(p.data.aliases ?? [])]) })),
    ...events.map((e) => ({ name: e.data.name, re: matcher([e.data.name, ...(e.data.aliases ?? [])]) })),
  ];

  const index = [
    ...articles.map((article) => {
      const haystack = `${article.data.title}\n${article.body}`;
      const tags = hubs.filter((h) => h.re.test(haystack)).map((h) => h.name);
      return {
        k: 'a',
        t: article.data.title,
        u: `/articles/${article.slug}/`,
        m: `${sourceNames(article.data).join(', ')}|${article.data.publishDate.toISOString()}`,
        x: `${excerptFrom(article.body, 420)} ${tags.join(' ')}`,
      };
    }),
    ...players.map((p) => ({
      k: 'p',
      t: p.data.name,
      u: `/players/${p.slug}/`,
      m: `Player · ${p.data.title} · ${federationName(p.data.federation)}`,
      x: (p.data.aliases ?? []).join(' '),
    })),
    ...events.map((e) => ({
      k: 'e',
      t: e.data.name,
      u: `/events/${e.slug}/`,
      m: `Event · ${e.data.frequency}`,
      x: `${(e.data.aliases ?? []).join(' ')} ${e.data.location}`,
    })),
  ];

  return new Response(JSON.stringify(index), {
    headers: { 'Content-Type': 'application/json' },
  });
}
