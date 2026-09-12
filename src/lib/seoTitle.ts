// Article headlines are deliberately full-sentence and often long (that's
// the editorial voice -- see the drafting prompt), which is fine for the
// on-page <h1> but not for the <title> tag: search engines truncate/ignore
// title tags past ~70 characters, and search consoles flag it. Rather than
// shortening the real headline, give the <title> tag its own, possibly
// truncated, version with the site name appended.
const SITE_SUFFIX = ' | The Chess Herald';
const MAX_LENGTH = 70;

export function seoTitle(pageTitle: string): string {
  const withSuffix = `${pageTitle}${SITE_SUFFIX}`;
  if (withSuffix.length <= MAX_LENGTH) return withSuffix;

  const budget = MAX_LENGTH - SITE_SUFFIX.length - 1; // -1 for the ellipsis
  const cut = pageTitle.slice(0, budget);
  const lastSpace = cut.lastIndexOf(' ');
  const truncated = lastSpace > 0 ? cut.slice(0, lastSpace) : cut;
  return `${truncated}…${SITE_SUFFIX}`;
}
