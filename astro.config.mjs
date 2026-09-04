import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';
import { visit } from 'unist-util-visit';

// Every link in an article body (whether hand-written or AI-drafted) points
// off-site -- a source article, a tournament page, a Wikimedia Commons file.
// None of them should navigate the reader away from Chessori in the same
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

export default defineConfig({
  site: 'https://chessori.com',
  output: 'static',
  integrations: [sitemap()],
  markdown: {
    rehypePlugins: [externalLinksNewTab],
  },
});
