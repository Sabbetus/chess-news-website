import { getCollection, type CollectionEntry } from 'astro:content';
import top100 from '../../data/fide-top100.json';

export type RankedPlayer = (typeof top100.players)[number];
export const TOP100 = top100;

// Drafts render only in a preview build (PREVIEW_DRAFTS=1 npm run build), so
// reviewers can see reference pages before they go live.
const SHOW_DRAFTS = import.meta.env.PREVIEW_DRAFTS === '1' || process.env.PREVIEW_DRAFTS === '1';
export const isVisible = (entry: { data: { reviewStatus: string } }) =>
  entry.data.reviewStatus === 'published' || SHOW_DRAFTS;

// FIDE's own three-letter codes, which are not ISO codes (ENG, IRI, SLO...).
// Anything unlisted shows as its code.
const FEDERATIONS: Record<string, string> = {
  ARM: 'Armenia', AUT: 'Austria', AZE: 'Azerbaijan', BUL: 'Bulgaria', CHN: 'China', CZE: 'Czechia',
  ENG: 'England', ESP: 'Spain', FID: 'FIDE flag', FRA: 'France', GER: 'Germany', GRE: 'Greece',
  HUN: 'Hungary', IND: 'India', IRI: 'Iran', ISR: 'Israel', MEX: 'Mexico', NED: 'Netherlands',
  NOR: 'Norway', POL: 'Poland', ROU: 'Romania', RUS: 'Russia', SLO: 'Slovenia', SRB: 'Serbia',
  TUR: 'Türkiye', UKR: 'Ukraine', USA: 'United States', UZB: 'Uzbekistan', VIE: 'Vietnam',
  CRO: 'Croatia', SWE: 'Sweden', DEN: 'Denmark', FIN: 'Finland', ITA: 'Italy', PER: 'Peru',
  CUB: 'Cuba', ARG: 'Argentina', BRA: 'Brazil', CAN: 'Canada', GEO: 'Georgia', KAZ: 'Kazakhstan',
  SUI: 'Switzerland', BEL: 'Belgium', LTU: 'Lithuania', LAT: 'Latvia', EST: 'Estonia', ISL: 'Iceland',
};
export const federationName = (code: string) => FEDERATIONS[code] ?? code;

export const periodLabel = (period: string) =>
  new Date(`${period}-01T00:00:00Z`).toLocaleDateString('en-US', { month: 'long', year: 'numeric', timeZone: 'UTC' });

export const initials = (name: string) =>
  name
    .split(/\s+/)
    .filter((w) => /^[\p{Lu}]/u.test(w))
    .slice(0, 2)
    .map((w) => w[0])
    .join('');

export const ageOn = (born: Date, on = new Date()) => {
  let age = on.getUTCFullYear() - born.getUTCFullYear();
  const beforeBirthday =
    on.getUTCMonth() < born.getUTCMonth() ||
    (on.getUTCMonth() === born.getUTCMonth() && on.getUTCDate() < born.getUTCDate());
  return beforeBirthday ? age - 1 : age;
};

export async function playerPages() {
  return (await getCollection('players')).filter(isVisible);
}
export async function eventPages() {
  return (await getCollection('events')).filter(isVisible);
}

// Published articles that mention any of the given full names in their title
// or body, newest first. Full names only -- a bare surname collides (the
// Javokhir/Komil Sindarov case in scripts/draft.py).
export async function articlesMentioning(aliases: string[]): Promise<CollectionEntry<'articles'>[]> {
  if (aliases.length === 0) return [];
  const escaped = aliases.map((a) => a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const pattern = new RegExp(`(?<![\\p{L}])(?:${escaped.join('|')})(?![\\p{L}])`, 'u');
  const articles = await getCollection('articles', ({ data }) => data.reviewStatus === 'published');
  return articles
    .filter((a) => pattern.test(a.data.title) || pattern.test(a.body))
    .sort((a, b) => b.data.publishDate.valueOf() - a.data.publishDate.valueOf());
}

export const shortDate = (d: Date) =>
  d.toLocaleDateString('en-US', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
export const longDate = (d: Date) =>
  d.toLocaleDateString('en-US', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' });
const monthName = (d: Date) => d.toLocaleDateString('en-US', { month: 'long', timeZone: 'UTC' });
// "January 15–31, 2027", "January 30 – February 12, 2027" -- en-US order, to
// match the dates everywhere else on the site.
export const dateRange = (start?: Date, end?: Date) => {
  if (!start) return 'Dates to be announced';
  if (!end) return longDate(start);
  const [sy, ey] = [start.getUTCFullYear(), end.getUTCFullYear()];
  if (sy !== ey) return `${longDate(start)} – ${longDate(end)}`;
  if (start.getUTCMonth() === end.getUTCMonth())
    return `${monthName(start)} ${start.getUTCDate()}–${end.getUTCDate()}, ${ey}`;
  return `${monthName(start)} ${start.getUTCDate()} – ${monthName(end)} ${end.getUTCDate()}, ${ey}`;
};

export const EVENT_CATEGORIES: { id: CollectionEntry<'events'>['data']['category']; label: string }[] = [
  { id: 'cycle', label: 'World Championship cycle' },
  { id: 'rapid-blitz', label: 'Rapid & blitz world titles' },
  { id: 'elite', label: 'Elite invitationals' },
  { id: 'open', label: 'Major opens' },
  { id: 'team', label: 'Team events and leagues' },
  { id: 'online', label: 'Online series' },
];

// schema.org about/mentions for an article: the player and event pages it
// names (full names/aliases only, same rule as articlesMentioning). Whoever
// the headline names is what the piece is "about"; the rest are "mentions".
export async function articleEntities(article: CollectionEntry<'articles'>, site: URL) {
  const [players, events] = await Promise.all([playerPages(), eventPages()]);
  const hubs = [
    ...players.map((p) => ({ type: 'Person', name: p.data.name, aliases: [p.data.name, ...(p.data.aliases ?? [])], path: `/players/${p.slug}/` })),
    // Thing, not SportsEvent: Google validates every SportsEvent node as an
    // event listing and flags these name-and-link references for missing
    // startDate/location (Search Console, 2026-10-04). The event page itself
    // carries the full SportsEvent markup.
    ...events.map((e) => ({ type: 'Thing', name: e.data.name, aliases: [e.data.name, ...(e.data.aliases ?? [])], path: `/events/${e.slug}/` })),
  ];
  const about: object[] = [];
  const mentions: { pos: number; node: object }[] = [];
  const title = article.data.title;
  for (const h of hubs) {
    const escaped = h.aliases.map((a) => a.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const re = new RegExp(`(?<![\\p{L}])(?:${escaped.join('|')})(?![\\p{L}])`, 'u');
    const node = { '@type': h.type, name: h.name, url: new URL(h.path, site).toString() };
    const bodyHit = article.body.search(re);
    // Headlines use surnames ("Sindarov Within Two Points of Caruana"), so a
    // player whose full name is in the body and surname in the headline is
    // what the piece is about too.
    const surname = h.type === 'Person' ? h.name.split(' ').pop()! : '';
    const surnameInTitle =
      surname.length >= 3 && new RegExp(`(?<![\\p{L}])${surname.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}(?![\\p{L}])`, 'u').test(title);
    if (re.test(title) || (bodyHit >= 0 && surnameInTitle)) about.push(node);
    else if (bodyHit >= 0) mentions.push({ pos: bodyHit, node });
  }
  mentions.sort((a, b) => a.pos - b.pos);
  return { about, mentions: mentions.slice(0, 10).map((m) => m.node) };
}
