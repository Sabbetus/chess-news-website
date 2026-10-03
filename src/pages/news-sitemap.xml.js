import { getCollection } from 'astro:content';

// Google News sitemap: articles published in the last 48 hours only (Google's
// rule). Built with the site, and the site rebuilds at least daily when the
// day's batch is merged, so the window stays current.
const WINDOW_MS = 48 * 60 * 60 * 1000;

const escape = (s) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');

export async function GET(context) {
  const cutoff = Date.now() - WINDOW_MS;
  const articles = (await getCollection('articles', ({ data }) => data.reviewStatus === 'published'))
    .filter((a) => a.data.publishDate.valueOf() >= cutoff)
    .sort((a, b) => b.data.publishDate.valueOf() - a.data.publishDate.valueOf());

  const urls = articles
    .map(
      (a) => `  <url>
    <loc>${new URL(`/articles/${a.slug}/`, context.site).toString()}</loc>
    <news:news>
      <news:publication><news:name>The Chess Herald</news:name><news:language>en</news:language></news:publication>
      <news:publication_date>${a.data.publishDate.toISOString()}</news:publication_date>
      <news:title>${escape(a.data.title)}</news:title>
    </news:news>
  </url>`
    )
    .join('\n');

  const body = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
${urls}
</urlset>
`;
  return new Response(body, { headers: { 'Content-Type': 'application/xml; charset=utf-8' } });
}
