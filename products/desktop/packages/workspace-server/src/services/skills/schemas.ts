import type { ExportedSkill as SharedExportedSkill } from "@posthog/shared";
import { z } from "zod";

export const skillSource = z.enum([
  "bundled",
  "user",
  "repo",
  "marketplace",
  "codex",
]);

export const skillInfo = z.object({
  name: z.string(),
  description: z.string(),
  source: skillSource,
  path: z.string(),
  repoName: z.string().optional(),
  editable: z.boolean(),
  skillMdBytes: z.number(),
});

export const listSkillsOutput = z.array(skillInfo);

export const skillFileEntry = z.object({
  // Path relative to the skill directory, using "/" separators.
  path: z.string(),
  size: z.number(),
});

export const skillContentsInput = z.object({
  skillPath: z.string(),
});

export const skillContentsOutput = z.object({
  files: z.array(skillFileEntry),
});

export const readSkillFileInput = z.object({
  skillPath: z.string(),
  filePath: z.string(),
});

export const readSkillFileOutput = z.string().nullable();

export const skillScope = z.enum(["user", "repo"]);

export const createSkillInput = z.object({
  scope: skillScope,
  repoPath: z.string().optional(),
  name: z.string(),
});

export const skillPathOutput = z.object({
  path: z.string(),
});

export const saveSkillManifestInput = z.object({
  skillPath: z.string(),
  name: z.string(),
  description: z.string(),
  body: z.string(),
});

export const saveSkillFileInput = z.object({
  skillPath: z.string(),
  filePath: z.string(),
  content: z.string(),
});

export const renameSkillFileInput = z.object({
  skillPath: z.string(),
  fromPath: z.string(),
  toPath: z.string(),
});

export const deleteSkillFileInput = z.object({
  skillPath: z.string(),
  filePath: z.string(),
});

export const deleteSkillInput = z.object({
  skillPath: z.string(),
});

export const exportSkillInput = z.object({
  skillPath: z.string(),
});

export const exportedSkillFile = z.object({
  // Path relative to the skill directory, using "/" separators.
  path: z.string(),
  content: z.string(),
});

// Pinned to the shared ExportedSkill contract so the shapes cannot drift.
export const exportSkillOutput = z.object({
  name: z.string(),
  description: z.string(),
  body: z.string(),
  files: z.array(exportedSkillFile),
  /** Files excluded from the export (binary or oversized). */
  skipped: z.array(z.string()),
}) satisfies z.ZodType<SharedExportedSkill & { skipped: string[] }>;

export const importCodexSkillInput = z.object({
  skillPath: z.string(),
  overwrite: z.boolean().optional(),
});

export const installTeamSkillInput = z.object({
  name: z.string(),
  description: z.string(),
  body: z.string(),
  files: z.array(exportedSkillFile),
  overwrite: z.boolean().optional(),
}) satisfies z.ZodType<SharedExportedSkill & { overwrite?: boolean }>;

export type ExportedSkill = z.infer<typeof exportSkillOutput>;
export type InstallTeamSkillInput = z.infer<typeof installTeamSkillInput>;

export const bundleLocalSkillInput = z.object({
  name: z.string().min(1),
  source: z.enum(["user", "repo", "marketplace", "codex"]),
  path: z.string().min(1),
});

export const bundleLocalSkillOutput = z.object({
  name: z.string(),
  source: z.enum(["user", "repo", "marketplace", "codex"]),
  fileName: z.string(),
  contentType: z.literal("application/zip"),
  contentBase64: z.string(),
  contentSha256: z.string(),
  size: z.number().int().positive(),
});

export const resolveSkillDependenciesInput = z.array(bundleLocalSkillInput);
export const resolveSkillDependenciesOutput = z.array(bundleLocalSkillInput);

export type BundleLocalSkillInput = z.infer<typeof bundleLocalSkillInput>;
export type BundleLocalSkillOutput = z.infer<typeof bundleLocalSkillOutput>;
export type SkillBundleRef = z.infer<typeof bundleLocalSkillInput>;
export type SkillInfo = z.infer<typeof skillInfo>;
export type SkillScope = z.infer<typeof skillScope>;
export type CreateSkillInput = z.infer<typeof createSkillInput>;
export type SkillSource = z.infer<typeof skillSource>;
export type SkillFileEntry = z.infer<typeof skillFileEntry>;
export type SkillContents = z.infer<typeof skillContentsOutput>;
export type UploadableSkillSource = BundleLocalSkillInput["source"];
