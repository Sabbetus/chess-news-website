import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: 'https://chessori.com',
  output: 'static',
  integrations: [sitemap()],
});
