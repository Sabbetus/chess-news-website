import { readdirSync, readFileSync } from 'node:fs';
import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import { visit } from 'unist-util-visit';

// Every link in an article body (whether hand-written or AI-drafted) points
// off-site -- a source article, a tournament page, a Wikimedia Commons file.
// None of them should navigate the reader away from The Chess Herald in the same
// tab, so this rewrites every <a href="http(s)://..."> produced from
// Markdown to open in a new tab, site-wide, without relying on every
// caller (including future AI-generated content) remembering to add it.
function externalLinksNewTab() {
  return (tree) => {
    visit(tree, 'element', (node) => {
      if (node.tagName !== 'a') return;
      const href = node.properties?.href;
      if (typeof href !== 'string' || !/^https?:\/\//.test(href)) return;
      node.properties.target = '_blank';
      const rel = new Set((node.properties.rel || []).concat(['noopener', 'noreferrer']));
      node.properties.rel = Array.from(rel);
    });
  };
}

// Article slug -> its own last-changed date, read straight from the content
// files at config time. The sitemap integration doesn't see frontmatter, so
// without this every URL ships with no lastmod at all and crawlers get no
// freshness signal for a site whose whole point is being current.
function articleLastmod() {
  const dir = new URL('./src/content/articles/', import.meta.url);
  const dates = new Map();
  for (const name of readdirSync(dir)) {
    if (!name.endsWith('.md')) continue;
    const text = readFileSync(new URL(name, dir), 'utf-8');
    const frontmatter = text.split('---')[1] ?? '';
    // updatedDate when a piece has been corrected, publishDate otherwise --
    // matching the dateModified the article page itself reports.
    const updated = frontmatter.match(/^updatedDate:\s*"?(\d{4}-\d{2}-\d{2})/m);
    const published = frontmatter.match(/^publishDate:\s*"?(\d{4}-\d{2}-\d{2})/m);
    const date = updated?.[1] ?? published?.[1];
    if (date) dates.set(name.replace(/\.md$/, ''), date);
  }
  return dates;
}

const ARTICLE_LASTMOD = articleLastmod();

export default defineConfig({
  site: 'https://chessherald.com',
  output: 'static',
  integrations: [
    sitemap({
      serialize(item) {
        const slug = item.url.match(/\/articles\/([^/]+)\/$/)?.[1];
        const date = slug && ARTICLE_LASTMOD.get(slug);
        // Only articles carry a meaningful per-URL date. Listing pages change
        // whenever any article does, so stamping them with a build time would
        // be noise rather than signal, and they're left without one.
        if (date) item.lastmod = new Date(`${date}T00:00:00Z`).toISOString();
        return item;
      },
    }),
  ],
  markdown: {
    rehypePlugins: [externalLinksNewTab],
  },
});
