const WORDS_PER_MINUTE = 200;

export function estimateReadMinutes(bodyMarkdown: string): number {
  const words = bodyMarkdown.trim().split(/\s+/).filter(Boolean).length;
  return Math.max(1, Math.round(words / WORDS_PER_MINUTE));
}
