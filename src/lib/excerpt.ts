// Cards and the lead dek show a short excerpt rather than requiring a
// separate frontmatter field -- derived from the article body so the
// drafting pipeline doesn't need to produce yet another string.
export function excerptFrom(bodyMarkdown: string, maxLen = 200): string {
  const plain = bodyMarkdown
    .replace(/^#.*$/gm, '')
    .replace(/[*_`>#]/g, '')
    .replace(/\[([^\]]+)\]\([^)]+\)/g, '$1')
    .replace(/\s+/g, ' ')
    .trim();

  if (plain.length <= maxLen) return plain;
  const cut = plain.slice(0, maxLen);
  const lastSpace = cut.lastIndexOf(' ');
  return `${cut.slice(0, lastSpace)}…`;
}
