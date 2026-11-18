import rss from '@astrojs/rss';
import { getCollection } from 'astro:content';
import { excerptFrom } from '../lib/excerpt';
import { publishedAt } from '../lib/publishedAt';
import { getImage } from 'astro:assets';
import { LENS_META } from '../lib/lens';

export async function GET(context) {
  const articles = (await getCollection('articles', ({ data }) => data.reviewStatus === 'published')).sort(
    (a, b) => publishedAt(b).valueOf() - publishedAt(a).valueOf()
  );

  // Each item's photo (a 1200px JPEG, like the social card) and its section,
  // so feed readers show a picture and a category (audit, 2026-11-16).
  const images = new Map();
  for (const article of articles) {
    if (!article.data.image) continue;
    const img = await getImage({ src: article.data.image.src, width: 1200, format: 'jpg' });
    images.set(article.slug, new URL(img.src, context.site).toString());
  }
  const escapeXml = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/"/g, '&quot;');

  return rss({
    // RSS 2.0's own <author> element is specified as an email address --
    // @astrojs/rss types it as one too -- so a plain byline there is invalid
    // and gets flagged by feed validators. dc:creator is the element actually
    // meant for a display name, and is what readers look for.
    xmlns: { dc: 'http://purl.org/dc/elements/1.1/', media: 'http://search.yahoo.com/mrss/' },
    title: 'The Chess Herald',
    description:
      'Daily chess news from around the world, every story linked back to its source.',
    site: context.site,
    items: articles.map((article) => ({
      title: article.data.title,
      pubDate: publishedAt(article),
      // Not socialCopy -- that field is written for X and Facebook, so it
      // carries hashtags, emoji and "full breakdown inside" style CTAs that
      // read as spam in a feed reader. An excerpt of the piece itself is
      // what a subscriber is actually after, and matches the meta
      // description the same article serves on the web.
      description: excerptFrom(article.body, 200),
      link: `/articles/${article.slug}/`,
      categories: [LENS_META[article.data.lens]?.label].filter(Boolean),
      customData:
        '<dc:creator>Claude Henry</dc:creator>' +
        (images.has(article.slug) ? `<media:content url="${escapeXml(images.get(article.slug))}" medium="image" type="image/jpeg"/>` : ''),
    })),
  });
}
