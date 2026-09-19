// A merged article (see additionalSources in config.ts) credits every
// outlet whose coverage went into it, not just the primary source -- the
// article detail page's byline already does this; card/listing contexts
// (homepage, archive, continent, lens, search) need the same label rather
// than silently dropping back to the primary source alone.
export function sourceNames(data: { sourceName: string; additionalSources?: { sourceName: string }[] }): string[] {
  return [data.sourceName, ...(data.additionalSources ?? []).map((s) => s.sourceName)];
}

// "Source: FIDE" / "Sources: FIDE, Chess.com" -- singular/plural label to
// match the article detail page's own byline wording.
export function sourceLabel(data: { sourceName: string; additionalSources?: { sourceName: string }[] }): string {
  const names = sourceNames(data);
  return `${names.length === 1 ? 'Source' : 'Sources'}: ${names.join(', ')}`;
}
