import type { CollectionEntry } from 'astro:content';

// The moment an article went live when we know it (stamped at deploy), else
// its publishDate (midnight UTC of that day).
export const publishedAt = (article: CollectionEntry<'articles'>): Date =>
  article.data.publishedAt ?? article.data.publishDate;
