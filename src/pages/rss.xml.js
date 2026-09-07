import rss from '@astrojs/rss';
import { getCollection } from 'astro:content';
import { excerptFrom } from '../lib/excerpt';

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
      // Not socialCopy -- that field is written for X and Facebook, so it
      // carries hashtags, emoji and "full breakdown inside" style CTAs that
      // read as spam in a feed reader. An excerpt of the piece itself is
      // what a subscriber is actually after, and matches the meta
      // description the same article serves on the web.
      description: excerptFrom(article.body, 200),
      link: `/articles/${article.slug}/`,
      author: 'Claude Henry',
    })),
  });
}
