// Generates the fixed 1200x630 (1.91:1) social-card crop for every
// published article's photo, run as an astro:build:done hook (see
// astro.config.mjs) after the main Astro build finishes.
//
// This exists as hand-written Sharp rather than going through Astro's own
// getImage()/<Image> pipeline (as ArticleThumb.astro and the article page's
// jsonLdImage still do) because Astro's built-in Sharp image service only
// ever exposes Sharp's `position` as a fixed named gravity (top/center/
// bottom/...) -- there is no percentage-offset option, the same limitation
// ArticleThumb.astro works around with a two-stage server-crop + CSS
// object-position trick. That trick only works because a browser renders
// the second stage; a social platform just embeds the raw file we hand it,
// so there's no second stage available -- the correct crop has to be baked
// into the one file directly. Sharp's own `.extract()` can cut an exact
// pixel rectangle at any offset, which is what this uses.
//
// Caught live: with no headroom logic at all (a literal position="top"
// crop, same as ArticleThumb.astro before its own fix), a portrait source
// scaled to the card's 1200px width and cropped to 630px tall showed only
// the very top of the subject's head -- unusable on X. TOP_BIAS below
// matches ArticleThumb.astro's own tuning (see global.css's
// .thumb-photo--headroom) so a shared card reads consistent with the
// on-site crop of the same photo, not a coincidentally different one.

import { mkdir, readdir, readFile, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import sharp from 'sharp';

const ROOT = fileURLToPath(new URL('..', import.meta.url));
const ARTICLES_DIR = path.join(ROOT, 'src/content/articles');

const OUT_WIDTH = 1200;
const OUT_HEIGHT = 630;
const TOP_BIAS = 0.3;

function parseFrontmatter(raw) {
  const match = raw.match(/^---\n([\s\S]*?)\n---/);
  if (!match) return null;
  const frontmatter = match[1];
  const reviewStatus = frontmatter.match(/^reviewStatus:\s*"([^"]+)"/m)?.[1];
  const imageSrc = frontmatter.match(/^image:\n(?:.*\n)*?\s+src:\s*"([^"]+)"/m)?.[1];
  return { reviewStatus, imageSrc };
}

export default async function generateSocialImages(outDirUrl) {
  const outDir = fileURLToPath(outDirUrl);
  const socialDir = path.join(outDir, 'social');
  await mkdir(socialDir, { recursive: true });

  const files = (await readdir(ARTICLES_DIR)).filter((name) => name.endsWith('.md'));

  for (const file of files) {
    const slug = file.replace(/\.md$/, '');
    const raw = await readFile(path.join(ARTICLES_DIR, file), 'utf-8');
    const { reviewStatus, imageSrc } = parseFrontmatter(raw) ?? {};
    if (reviewStatus !== 'published' || !imageSrc) continue;

    const sourcePath = path.resolve(ARTICLES_DIR, imageSrc);
    let base;
    try {
      base = sharp(sourcePath).rotate();
    } catch {
      continue; // Source file missing/unreadable -- BaseLayout falls back to the site default og-image.
    }
    const meta = await base.metadata();
    if (!meta.width || !meta.height) continue;

    const scaleForWidth = OUT_WIDTH / meta.width;
    const scaledHeight = Math.round(meta.height * scaleForWidth);

    let pipeline;
    if (scaledHeight >= OUT_HEIGHT) {
      // Source is narrower (relatively taller) than the card ratio: crop
      // height. A literal top edge (offset 0) cuts too tight -- same
      // failure mode as ArticleThumb.astro's old position="top" default --
      // so bias the window TOP_BIAS of the way down through the spare
      // vertical room instead of starting right at the hairline.
      const offset = Math.round((scaledHeight - OUT_HEIGHT) * TOP_BIAS);
      pipeline = sharp(sourcePath)
        .rotate()
        .resize({ width: OUT_WIDTH })
        .extract({ left: 0, top: offset, width: OUT_WIDTH, height: OUT_HEIGHT });
    } else {
      // Source is wider than the card ratio: crop width instead, from the
      // center -- there's no headroom axis to protect on this side, and a
      // wide shot's subject is rarely pinned to one horizontal edge.
      const scaleForHeight = OUT_HEIGHT / meta.height;
      const scaledWidth = Math.round(meta.width * scaleForHeight);
      const offset = Math.max(0, Math.round((scaledWidth - OUT_WIDTH) / 2));
      pipeline = sharp(sourcePath)
        .rotate()
        .resize({ height: OUT_HEIGHT })
        .extract({ left: offset, top: 0, width: OUT_WIDTH, height: OUT_HEIGHT });
    }

    const buffer = await pipeline.jpeg({ quality: 82 }).toBuffer();
    await writeFile(path.join(socialDir, `${slug}.jpg`), buffer);
  }
}
