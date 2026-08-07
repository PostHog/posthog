import { z } from "zod";

export const releaseItem = z.object({
  version: z.string(),
  name: z.string(),
  notes: z.string(),
  date: z.string().nullable(),
  isPrerelease: z.boolean(),
  htmlUrl: z.string(),
});

export const listReleasesInput = z
  .object({ expectVersion: z.string().optional() })
  .optional();

export const listReleasesOutput = z.object({
  releases: z.array(releaseItem),
});

export type ReleaseItem = z.infer<typeof releaseItem>;
export type ListReleasesOutput = z.infer<typeof listReleasesOutput>;
