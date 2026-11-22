// Placement rule for quoted posts on X, shared by the markdown plugin
// (inline-tweets.mjs) and the article page. No package imports, so the
// Python test job can run it with plain node (2026-11-22: importing
// js-yaml there failed every "Pipeline tests" run).
const norm = (s) =>
  String(s)
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase();

function authorKeys(tweet) {
  const words = String(tweet.author ?? '')
    .split(/\s+/)
    .filter((w) => w.length >= 3);
  const keys = [];
  if (words.length) keys.push(words[words.length - 1]);
  // "Vachier_Lagrave" is written "Vachier-Lagrave" in the text.
  if (tweet.handle) keys.push(tweet.handle, tweet.handle.replace(/_/g, '-'), tweet.handle.replace(/_/g, ' '));
  return keys.map(norm);
}

const STOP = new Set(
  ('the and for that this with from have was were are but not you all his her its our their they them about into over '
    + 'after before when what which who will would there here just than then also more most some very been being has had '
    + 'game games chess player players event').split(' '),
);
const words = (t) => new Set((t.match(/[a-z][a-z'-]{3,}/g) ?? []).filter((w) => !STOP.has(w)));
// A paragraph that says a post was made is about the post.
const POSTED = /\b(tweet(ed)?|posted|wrote|on x|social media|open letter)\b/;

/** Index of the paragraph a tweet belongs after, or -1.
 *  It must name the author and either say a post was made or share at
 *  least two content words with the tweet (2026-11-22: a So tweet on the
 *  format landed after a paragraph that only listed him in a pairing);
 *  of those, the one sharing the most words wins. */
export function tweetParagraphIndex(paragraphs, tweet) {
  const texts = paragraphs.map(norm);
  if (tweet.after) {
    const i = texts.findIndex((t) => t.includes(norm(tweet.after)));
    if (i >= 0) return i;
  }
  const keys = authorKeys(tweet);
  const tw = words(norm(tweet.text));
  let best = -1;
  let bestScore = 0;
  for (const [i, t] of texts.entries()) {
    const named = keys.some((k) =>
      new RegExp(`(^|[^a-z])${k.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}([^a-z]|$)`).test(t),
    );
    if (!named) continue;
    const shared = [...words(t)].filter((w) => tw.has(w)).length;
    if (!POSTED.test(t) && shared < 2) continue;
    const score = shared + (POSTED.test(t) ? 2 : 0) + 1;
    if (score > bestScore) {
      best = i;
      bestScore = score;
    }
  }
  return best;
}

/** Plain paragraphs of a markdown body (headings and blank lines skipped). */
export function markdownParagraphs(body) {
  return String(body)
    .split(/\n\s*\n/)
    .map((p) => p.trim())
    .filter((p) => p && !p.startsWith('#') && !/^\*\*[^*]+\*\*$/.test(p));
}

