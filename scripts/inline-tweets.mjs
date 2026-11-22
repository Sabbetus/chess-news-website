// Places each quoted post on X right after the paragraph that discusses it,
// instead of in a block at the end of the article (user's call, 2026-11-22:
// "a bunch of tweets randomly at the end"). A tweet may name its paragraph
// with `after` (a short phrase from it); otherwise it goes after the first
// paragraph naming its author (surname or handle). A tweet no paragraph
// matches stays in the end block (TweetQuotes.astro), which uses the same
// test via tweetParagraphIndex.
import { readFileSync } from 'node:fs';
import yaml from 'js-yaml';
import { tweetParagraphIndex, markdownParagraphs } from './inline-tweets-core.mjs';

export { tweetParagraphIndex, markdownParagraphs };

const textOf = (node) => (node.type === 'text' ? node.value : (node.children ?? []).map(textOf).join(''));

function fmtDate(iso) {
  if (!iso) return '';
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    timeZone: 'UTC',
  });
}

const el = (tagName, properties, children) => ({ type: 'element', tagName, properties, children });
const txt = (value) => ({ type: 'text', value });

function quoteNode(tweet) {
  const footer = [
    el('a', { href: tweet.url, target: '_blank', rel: 'noopener nofollow' }, [
      txt(`${tweet.author} `),
      el('span', { className: ['tweet-handle'] }, [txt(`@${tweet.handle}`)]),
    ]),
  ];
  if (tweet.date) footer.push(el('span', { className: ['tweet-date'] }, [txt(` · ${fmtDate(tweet.date)}`)]));
  const paras = String(tweet.text)
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter(Boolean)
    .map((p) => el('p', {}, [txt(p)]));
  return el('blockquote', { className: ['tweet-quote', 'tweet-inline'], cite: tweet.url }, [
    ...paras,
    el('footer', {}, footer),
  ]);
}

function tweetsOf(path) {
  try {
    const fm = readFileSync(path, 'utf-8').split(/^---$/m)[1] ?? '';
    const data = yaml.load(fm) ?? {};
    return Array.isArray(data.tweetEmbeds) ? data.tweetEmbeds : [];
  } catch {
    return [];
  }
}

export default function inlineTweets() {
  return (tree, file) => {
    const path = file?.path ?? file?.history?.[0] ?? '';
    if (!path.includes('/content/articles/')) return;
    const tweets = tweetsOf(path);
    if (!tweets.length) return;
    // Top-level paragraphs only, in the same order markdownParagraphs sees
    // them (a bold-only paragraph is a section heading there).
    const paras = tree.children.filter(
      (n) =>
        n.type === 'element' &&
        n.tagName === 'p' &&
        !(n.children?.length === 1 && n.children[0].tagName === 'strong'),
    );
    const placed = new Map();
    for (const tweet of tweets) {
      const i = tweetParagraphIndex(paras.map(textOf), tweet);
      if (i < 0) continue;
      if (!placed.has(paras[i])) placed.set(paras[i], []);
      placed.get(paras[i]).push(quoteNode(tweet));
    }
    tree.children = tree.children.flatMap((n) => (placed.has(n) ? [n, ...placed.get(n)] : [n]));
  };
}
