import { defineCollection, z } from 'astro:content';

// Frontmatter is the source of truth for pipeline/review state, not git/PR
// state alone — this lets a future admin UI read/write the same data
// instead of needing a new data model.
const articles = defineCollection({
  type: 'content',
  schema: z.object({
    title: z.string(),
    publishDate: z.date(),
    sourceName: z.string(),
    sourceUrl: z.string().url(),
    lens: z.enum(['tournament-db', 'nordic-angle', 'organizer-pov']),
    selectionScore: z.number(),
    reviewStatus: z.enum(['draft', 'approved', 'published']),
    socialCopy: z.string().optional(),
  }),
});

export const collections = { articles };
