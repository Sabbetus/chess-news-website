// A merged article (see additionalSources in config.ts) credits every
// outlet whose coverage went into it, not just the primary source -- the
// article detail page's byline already does this; card/listing contexts
// (homepage, archive, continent, lens, search) need the same label rather
// than silently dropping back to the primary source alone.
type SourceData = { sourceName: string; sourceUrl: string; additionalSources?: { sourceName: string; sourceUrl: string }[] };

export function sourceNames(data: SourceData): string[] {
  return sourceEntries(data).map((s) => s.sourceName);
}

// Every source as its own {sourceName, sourceUrl} pair, primary first --
// for contexts (like the homepage lead) that link each name to its own
// URL rather than bundling all names under a single link to the primary
// source alone (the bug this was added to fix: the lead byline showed
// "Sources: FIDE, Chess.com" but the whole thing linked only to FIDE).
export function sourceEntries(data: SourceData): { sourceName: string; sourceUrl: string }[] {
  return [{ sourceName: data.sourceName, sourceUrl: data.sourceUrl }, ...(data.additionalSources ?? [])];
}

// "Source: FIDE" / "Sources: FIDE, Chess.com" -- singular/plural label to
// match the article detail page's own byline wording.
export function sourceLabel(data: { sourceName: string; additionalSources?: { sourceName: string }[] }): string {
  const names = sourceNames(data);
  return `${names.length === 1 ? 'Source' : 'Sources'}: ${names.join(', ')}`;
}
