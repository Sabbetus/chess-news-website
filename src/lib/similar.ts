// "Similar Articles" under each article: pieces about the same people,
// events and organizations first, then same lens/continent, then most
// recent. Used to be lens-or-continent only, so a Turlov interview showed
// three unrelated pieces from the same day instead of his earlier coverage.
import { getCollection, type CollectionEntry } from 'astro:content';
import { playerPages, eventPages } from './hubs';

type Article = CollectionEntry<'articles'>;

// Capitalized words that start sentences or headings, or are too generic to
// tie two stories together on their own.
const STOP = new Set(
  `the a an and or but of in on at to for with from by as is are was were this that these those
  his her their its it he she they we you i our my after before when while where how why what who
  chess fide world championship tournament olympiad round open cup grand prix rapid blitz classical
  women women's men team teams final finals game games match day week month year new first last
  gm im wgm wim fm cm herald september october november december january february march april may
  june july august monday tuesday wednesday thursday friday saturday sunday`.split(/\s+/)
);

// Two or more adjacent capitalized words ("Timur Turlov", "Global Chess
// Festival") -- the names a reader would recognize as "the same story".
function names(text: string): Set<string> {
  const out = new Set<string>();
  const add = (seg: string[]) => {
    if (seg.length >= 2) out.add(seg.join(' ').toLowerCase());
    // Surnames carry most of the signal when the first name is dropped
    // later in a piece ("Turlov said"), so keep the last word too.
    const last = seg[seg.length - 1];
    if (seg.length >= 2 && last.length >= 4) out.add(last.toLowerCase());
  };
  const re = /\b([A-Z][\p{L}'’-]+(?:\s+[A-Z][\p{L}'’-]+)+)/gu;
  for (const m of text.matchAll(re)) {
    // Split one capitalized run into separate names at filler words and
    // possessives: "Judit Polgar's Global Chess Festival" is "Judit
    // Polgar" plus "Global ... Festival", not one name.
    let seg: string[] = [];
    for (const raw of m[1].split(/\s+/)) {
      const possessive = /['’]s$/.test(raw);
      const word = raw.replace(/['’]s$/, '');
      if (STOP.has(word.toLowerCase())) {
        add(seg);
        seg = [];
        continue;
      }
      seg.push(word);
      if (possessive) {
        add(seg);
        seg = [];
      }
    }
    add(seg);
  }
  return out;
}

// Headlines are Title Case ("Judit Polgar Drops a Game..."), so names can't
// be read off them directly; instead keep the body's names that the
// headline also contains.
function inTitle(bodyNames: Set<string>, title: string): Set<string> {
  const t = ` ${title.toLowerCase().replace(/[^\p{L}\s'’-]/gu, ' ')} `;
  return new Set([...bodyNames].filter((n) => t.includes(` ${n} `) || t.includes(` ${n}'`) || t.includes(` ${n}’`)));
}

interface Profile {
  article: Article;
  names: Set<string>;
  titleNames: Set<string>;
  hubs: Set<string>;
}

let cache: Promise<Profile[]> | null = null;

async function profiles(): Promise<Profile[]> {
  if (!cache) {
    cache = (async () => {
      const [articles, players, events] = await Promise.all([
        getCollection('articles', ({ data }) => data.reviewStatus === 'published' && data.type !== 'recap'),
        playerPages(),
        eventPages(),
      ]);
      const hubAliases = [...players, ...events].map((h) => ({
        id: h.collection + ':' + h.slug,
        aliases: [h.data.name, ...(h.data.aliases ?? [])].map((a) => a.toLowerCase()),
      }));
      return articles.map((article) => {
        const text = `${article.data.title}\n${article.body}`;
        const lower = text.toLowerCase();
        const nameSet = names(article.body);
        return {
          article,
          names: nameSet,
          titleNames: inTitle(nameSet, article.data.title),
          hubs: new Set(hubAliases.filter((h) => h.aliases.some((a) => lower.includes(a))).map((h) => h.id)),
        };
      });
    })();
  }
  return cache;
}

const overlap = (a: Set<string>, b: Set<string>) => {
  let n = 0;
  for (const x of a) if (b.has(x)) n++;
  return n;
};

export async function similarArticles(article: Article, count = 3): Promise<Article[]> {
  const all = await profiles();
  const self = all.find((p) => p.article.slug === article.slug);
  const titleNames = self ? self.titleNames : new Set<string>();
  const scored = all
    .filter((p) => p.article.slug !== article.slug)
    .map((p) => {
      let score = 0;
      // Whoever the headline is about matters most: their name anywhere in
      // the other piece, more again if it's in that headline too. Shared
      // body mentions and player/event pages only break ties -- big events
      // like the Olympiad turn up in passing in half the archive.
      score += 6 * overlap(titleNames, p.names);
      score += 3 * overlap(titleNames, p.titleNames);
      if (self) {
        score += 1 * overlap(self.hubs, p.hubs);
        score += 1 * overlap(self.names, p.names);
      }
      if (p.article.data.lens === article.data.lens) score += 1;
      if (p.article.data.continent === article.data.continent) score += 1;
      return { p, score };
    });
  return scored
    .sort((a, b) => b.score - a.score || b.p.article.data.publishDate.valueOf() - a.p.article.data.publishDate.valueOf())
    .slice(0, count)
    .map((s) => s.p.article);
}
