import { z } from "zod";

export const marketplaceSkillRef = z.object({
  /** GitHub repository in "owner/repo" form. */
  source: z.string(),
  /** Skill directory name inside the repository. */
  skillId: z.string(),
});

export const marketplaceSearchInput = z.object({
  query: z.string(),
});

export const marketplaceSearchResult = z.object({
  id: z.string(),
  skillId: z.string(),
  name: z.string(),
  installs: z.number(),
  source: z.string(),
  installed: z.boolean(),
});

export const marketplaceSearchOutput = z.object({
  results: z.array(marketplaceSearchResult),
});

export const marketplacePreviewFile = z.object({
  // Path relative to the skill directory, using "/" separators.
  path: z.string(),
  size: z.number(),
  /** Null when the file is binary or too large to preview. */
  content: z.string().nullable(),
});

export const marketplacePreviewOutput = z.object({
  files: z.array(marketplacePreviewFile),
  hasScripts: z.boolean(),
});

export const marketplaceInstallInput = marketplaceSkillRef.extend({
  overwrite: z.boolean().optional(),
});

export const marketplaceInstallOutput = z.object({
  path: z.string(),
});

/** Shape of the skills.sh search API response (external boundary). */
export const skillsShSearchResponse = z.object({
  skills: z.array(
    z.object({
      id: z.string(),
      skillId: z.string(),
      name: z.string(),
      installs: z.number().optional(),
      source: z.string(),
    }),
  ),
});

export type MarketplaceSkillRef = z.infer<typeof marketplaceSkillRef>;
export type MarketplaceSearchOutput = z.infer<typeof marketplaceSearchOutput>;
export type MarketplacePreviewOutput = z.infer<typeof marketplacePreviewOutput>;
export type MarketplacePreviewFile = z.infer<typeof marketplacePreviewFile>;
