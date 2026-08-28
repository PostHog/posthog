import { z } from "zod";

export const openInAppInput = z.object({
  appId: z.string(),
  targetPath: z.string(),
});

export const setLastUsedInput = z.object({
  appId: z.string(),
});

export const copyPathInput = z.object({
  targetPath: z.string(),
});

export const externalAppType = z.enum([
  "editor",
  "terminal",
  "file-manager",
  "git-client",
]);

const detectedApplication = z.object({
  id: z.string(),
  name: z.string(),
  type: externalAppType,
  path: z.string(),
  command: z.string(),
  icon: z.string().optional(),
});

export const getDetectedAppsOutput = z.array(detectedApplication);
export const openInAppOutput = z.object({
  success: z.boolean(),
  error: z.string().optional(),
});
export const getLastUsedOutput = z.object({
  lastUsedApp: z.string().optional(),
});

export type OpenInAppInput = z.infer<typeof openInAppInput>;
export type SetLastUsedInput = z.infer<typeof setLastUsedInput>;
export type CopyPathInput = z.infer<typeof copyPathInput>;
export type DetectedApplication = z.infer<typeof detectedApplication>;
export type ExternalAppType = z.infer<typeof externalAppType>;
export type OpenInAppOutput = z.infer<typeof openInAppOutput>;
export type GetLastUsedOutput = z.infer<typeof getLastUsedOutput>;
