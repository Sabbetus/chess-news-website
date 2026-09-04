import rss from '@astrojs/rss';
import { getCollection } from 'astro:content';

export async function GET(context) {
  const articles = (await getCollection('articles', ({ data }) => data.reviewStatus === 'published')).sort(
    (a, b) => b.data.publishDate.valueOf() - a.data.publishDate.valueOf()
  );

  return rss({
    title: 'Chessori',
    description:
      'Curated chess news from around the world, with original analysis and tournament statistics. Every story linked back to its source.',
    site: context.site,
    items: articles.map((article) => ({
      title: article.data.title,
      pubDate: article.data.publishDate,
      description: article.data.socialCopy || article.data.title,
      link: `/articles/${article.slug}/`,
      author: 'Claude Henry',
    })),
  });
}
