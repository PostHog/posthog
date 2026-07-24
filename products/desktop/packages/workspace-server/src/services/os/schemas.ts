import { isSafeExternalUrl } from "@posthog/shared";
import { z } from "zod";

export const claudePermissionsOutput = z.object({
  allow: z.array(z.string()),
  deny: z.array(z.string()),
});
export type ClaudePermissions = z.infer<typeof claudePermissionsOutput>;

// Personalization synced from a file can be much larger than hand-typed
// instructions, but the prompt it lands in must stay bounded. Shared by
// `OsService`'s truncation and the session-start Zod validators
// (`startSessionInput`/`reconnectSessionInput` in ../agent/schemas) so the two
// stay equal — a synced file truncated to this length must not then fail the
// session-start length check.
export const USER_AGENT_INSTRUCTIONS_MAX_LENGTH = 20_000;

export const userAgentInstructionsSchema = z.object({
  path: z.string(),
  /** Home-relative form of `path` (e.g. `~/.claude/CLAUDE.md`), for display. */
  displayPath: z.string(),
  content: z.string(),
  truncated: z.boolean(),
});
export const userAgentInstructionsOutput =
  userAgentInstructionsSchema.nullable();
export type UserAgentInstructions = z.infer<typeof userAgentInstructionsSchema>;

export const selectAttachmentsInput = z.object({
  mode: z.enum(["files", "directories", "both"]).default("both"),
});
export type SelectAttachmentsMode = z.infer<
  typeof selectAttachmentsInput
>["mode"];

export const selectedAttachment = z.object({
  path: z.string(),
  kind: z.enum(["file", "directory"]),
});
export const selectAttachmentsOutput = z.array(selectedAttachment);
export type SelectedAttachment = z.infer<typeof selectedAttachment>;

export const selectFilesOutput = z.array(z.string());

export const checkWriteAccessInput = z.object({ directoryPath: z.string() });

export const messageBoxOptionsSchema = z.object({
  type: z.enum(["none", "info", "error", "question", "warning"]).optional(),
  title: z.string().optional(),
  message: z.string().optional(),
  detail: z.string().optional(),
  buttons: z.array(z.string()).optional(),
  defaultId: z.number().optional(),
  cancelId: z.number().optional(),
});
export type MessageBoxOptions = z.infer<typeof messageBoxOptionsSchema>;
export const showMessageBoxInput = z.object({
  options: messageBoxOptionsSchema,
});

export const openExternalInput = z.object({
  url: z
    .string()
    .refine(
      isSafeExternalUrl,
      "Only http(s) and mailto URLs may be opened externally",
    ),
});

export const searchDirectoriesInput = z.object({
  query: z.string(),
  searchRoot: z.string().optional(),
});

export const readFileAsDataUrlInput = z.object({
  filePath: z.string(),
  maxSizeBytes: z
    .number()
    .optional()
    .default(10 * 1024 * 1024),
});

export const saveClipboardTextInput = z.object({
  text: z.string(),
  originalName: z.string().optional(),
});

export const saveClipboardImageInput = z.object({
  base64Data: z.string(),
  mimeType: z.string(),
  originalName: z.string().optional(),
});

export const downscaleImageFileInput = z.object({
  filePath: z.string().min(1),
});

export const saveClipboardFileInput = z.object({
  base64Data: z.string(),
  originalName: z.string().optional(),
});

export interface SavedAttachment {
  path: string;
  name: string;
}

export interface ImageAttachment {
  path: string;
  name: string;
  mimeType: string;
}
