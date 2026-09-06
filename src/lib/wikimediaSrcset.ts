// Wikimedia thumbnail URLs encode their width directly in the path, e.g.
// https://thumb.wikimedia.org/.../1280px-Foo.jpg -- so a srcset covering
// several smaller widths can be built by string-rewriting an already-stored
// URL, with no re-fetch from Commons and no change to the drafting pipeline.
// images.py requests a flat 1200px width regardless of context, but the
// lead image only ever renders around ~680px CSS wide and grid cards far
// less than that -- shipping the full 1200px JPEG to every context was the
// single largest PageSpeed cost on the site.
const WIDTH_SEGMENT = /\/(\d+)px-/;

export function buildSrcset(url: string, widths: number[]): string | undefined {
  const match = url.match(WIDTH_SEGMENT);
  if (!match) return undefined; // not a resizable Commons thumb URL (e.g. a raw file URL) -- just use src as-is

  const originalWidth = parseInt(match[1], 10);
  const candidateWidths = widths.filter((w) => w < originalWidth);
  candidateWidths.push(originalWidth); // always include the original as the largest candidate

  return candidateWidths.map((w) => `${url.replace(WIDTH_SEGMENT, `/${w}px-`)} ${w}w`).join(', ');
}
