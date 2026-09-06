import { getCollection } from 'astro:content';
import { excerptFrom } from '../lib/excerpt';

// A small, static search index built at deploy time -- there's no backend
// to query, so the client fetches this once and filters it locally. Kept
// deliberately light (title/excerpt/tags only, no body) since it's fetched
// on every visitor's first search.
export async function GET() {
  const articles = (await getCollection('articles', ({ data }) => data.reviewStatus === 'published')).sort(
    (a, b) => b.data.publishDate.valueOf() - a.data.publishDate.valueOf()
  );

  const index = articles.map((article) => ({
    title: article.data.title,
    slug: article.slug,
    excerpt: excerptFrom(article.body, 140),
    sourceName: article.data.sourceName,
    publishDate: article.data.publishDate.toISOString(),
  }));

  return new Response(JSON.stringify(index), {
    headers: { 'Content-Type': 'application/json' },
  });
}
