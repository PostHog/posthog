import type {
  RequestPermissionRequest,
  PermissionOption as SdkPermissionOption,
} from "@agentclientprotocol/sdk";
import { effortLevelSchema } from "@posthog/shared/domain-types";
import { z } from "zod";
import { USER_AGENT_INSTRUCTIONS_MAX_LENGTH } from "../os/schemas";

export { effortLevelSchema };
export type { EffortLevel } from "@posthog/shared/domain-types";

// Session credentials schema
export const credentialsSchema = z.object({
  apiHost: z.string(),
  projectId: z.number(),
});

export type Credentials = z.infer<typeof credentialsSchema>;

// Session config schema
export const sessionConfigSchema = z.object({
  taskId: z.string(),
  taskRunId: z.string(),
  repoPath: z.string(),
  credentials: credentialsSchema,
  logUrl: z.string().optional(),
  /** The agent's session ID (for resume - SDK session ID for Claude, Codex's session ID for Codex) */
  sessionId: z.string().optional(),
  adapter: z.enum(["claude", "codex"]).optional(),
  /** Additional directories Claude can access beyond cwd (for worktree support) */
  additionalDirectories: z.array(z.string()).optional(),
  /** Permission mode to use for the session (e.g. "default", "acceptEdits", "plan", "bypassPermissions") */
  permissionMode: z.string().optional(),
  /**
   * Session ID of an imported Claude Code CLI transcript already present in
   * CLAUDE_CONFIG_DIR. Starts the session via loadSession so the prior
   * history is replayed to the client. Claude adapter only.
   */
  importedSessionId: z.string().optional(),
});

export type SessionConfig = z.infer<typeof sessionConfigSchema>;

// Sized for personalization synced from an AGENTS.md/CLAUDE.md file, which
// can be far larger than the 2000-char hand-typed settings field. Kept equal
// to OsService's truncation length (USER_AGENT_INSTRUCTIONS_MAX_LENGTH) or a
// synced file gets truncated to fit but still fails this check. Shared by
// startSessionInput and reconnectSessionInput below.
const customInstructionsField = z
  .string()
  .max(USER_AGENT_INSTRUCTIONS_MAX_LENGTH)
  .optional();

// Start session input/output

export const startSessionInput = z.object({
  taskId: z.string(),
  taskRunId: z.string(),
  repoPath: z.string(),
  apiHost: z.string(),
  projectId: z.number(),
  permissionMode: z.string().optional(),
  autoProgress: z.boolean().optional(),
  runMode: z.enum(["local", "cloud"]).optional(),
  adapter: z.enum(["claude", "codex"]).optional(),
  additionalDirectories: z.array(z.string()).optional(),
  customInstructions: customInstructionsField,
  /**
   * Replaces the PostHog system prompt entirely for this session. Used by
   * constrained, single-purpose surfaces (e.g. the canvas generator) that drive
   * the agent with their own prompt rather than the default coding prompt.
   * Uncapped, unlike `customInstructions`.
   */
  systemPromptOverride: z.string().optional(),
  /**
   * Tool names the agent must not use this session (passed to the Claude SDK).
   * Lets a sandboxed surface deny file/shell/network tools.
   */
  disallowedTools: z.array(z.string()).optional(),
  effort: effortLevelSchema.optional(),
  model: z.string().optional(),
  jsonSchema: z.record(z.string(), z.unknown()).nullish(),
  /**
   * Session ID of an imported Claude Code CLI transcript already present in
   * CLAUDE_CONFIG_DIR. Starts the session via loadSession so the prior
   * history is replayed to the client. Claude adapter only.
   */
  importedSessionId: z.string().optional(),
  /**
   * Whether rtk command-output compression is enabled for this session.
   * Defaults to enabled; false sets POSTHOG_RTK=0 on the agent environment.
   */
  rtkEnabled: z.boolean().optional(),
  /**
   * The user's spoken-narration setting at session start. Gates the agent's
   * speak tool and its prompt instructions. Strictly opt-in: only the desktop
   * sets it true (feature flag + setting); when absent the adapter leaves
   * narration off, so headless runs never load the tool.
   */
  spokenNarration: z.boolean().optional(),
});

export type StartSessionInput = z.infer<typeof startSessionInput>;

export const modelOptionSchema = z.object({
  modelId: z.string(),
  name: z.string(),
  description: z.string().nullish(),
  provider: z.string().optional(),
});

export type ModelOption = z.infer<typeof modelOptionSchema>;

const sessionConfigSelectOptionSchema = z.looseObject({
  value: z.string(),
  name: z.string(),
  description: z.string().nullish(),
  _meta: z.record(z.string(), z.unknown()).nullish(),
});

const sessionConfigSelectGroupSchema = z.looseObject({
  group: z.string(),
  name: z.string(),
  options: z.array(sessionConfigSelectOptionSchema),
  _meta: z.record(z.string(), z.unknown()).nullish(),
});

const sessionConfigSelectSchema = z.looseObject({
  id: z.string(),
  name: z.string(),
  type: z.literal("select"),
  currentValue: z.string(),
  options: z
    .array(sessionConfigSelectOptionSchema)
    .or(z.array(sessionConfigSelectGroupSchema)),
  category: z.string().nullish(),
  description: z.string().nullish(),
  _meta: z.record(z.string(), z.unknown()).nullish(),
});

const sessionConfigBooleanSchema = z.looseObject({
  id: z.string(),
  name: z.string(),
  type: z.literal("boolean"),
  currentValue: z.boolean(),
  category: z.string().nullish(),
  description: z.string().nullish(),
  _meta: z.record(z.string(), z.unknown()).nullish(),
});

export const sessionConfigOptionSchema = z.union([
  sessionConfigSelectSchema,
  sessionConfigBooleanSchema,
]);

export type SessionConfigOption = z.infer<typeof sessionConfigOptionSchema>;

export const sessionResponseSchema = z.object({
  sessionId: z.string(),
  channel: z.string(),
  configOptions: z.array(sessionConfigOptionSchema).optional(),
  // The adapter's negotiated steering capability from initialize
  // (`_meta.posthog.steering`): "native" folds a mid-turn message into the
  // running turn; "interrupt-resend" (legacy) or absent means the host must
  // cancel + resend instead. Drives the host's steer-vs-resend decision.
  steering: z.string().optional(),
});

export type SessionResponse = z.infer<typeof sessionResponseSchema>;

// Prompt input/output
export const contentBlockSchema = z.looseObject({
  type: z.string(),
  text: z.string().optional(),
  _meta: z.record(z.string(), z.unknown()).nullish(),
});

export const promptInput = z.object({
  sessionId: z.string(),
  prompt: z.array(contentBlockSchema),
  steer: z.boolean().optional(),
});

export type PromptInput = z.infer<typeof promptInput>;

export const promptOutput = z.object({
  stopReason: z.string(),
  _meta: z
    .object({
      interruptReason: z.string().optional(),
    })
    .optional(),
});

export type PromptOutput = z.infer<typeof promptOutput>;

// Cancel session input
export const cancelSessionInput = z.object({
  sessionId: z.string(),
});

// Interrupt reason schema
export const interruptReasonSchema = z.enum([
  "user_request",
  "moving_to_worktree",
]);
export type InterruptReason = z.infer<typeof interruptReasonSchema>;

// Cancel prompt input
export const cancelPromptInput = z.object({
  sessionId: z.string(),
  reason: interruptReasonSchema.optional(),
});

// Reconnect session input
export const reconnectSessionInput = z.object({
  taskId: z.string(),
  taskRunId: z.string(),
  repoPath: z.string(),
  apiHost: z.string(),
  projectId: z.number(),
  logUrl: z.string().optional(),
  sessionId: z.string().optional(),
  adapter: z.enum(["claude", "codex"]).optional(),
  /** Additional directories Claude can access beyond cwd (for worktree support) */
  additionalDirectories: z.array(z.string()).optional(),
  permissionMode: z.string().optional(),
  model: z.string().optional(),
  customInstructions: customInstructionsField,
  effort: effortLevelSchema.optional(),
  jsonSchema: z.record(z.string(), z.unknown()).nullish(),
  /** See startSessionInput.rtkEnabled. */
  rtkEnabled: z.boolean().optional(),
  /** See startSessionInput.spokenNarration. */
  spokenNarration: z.boolean().optional(),
});

export type ReconnectSessionInput = z.infer<typeof reconnectSessionInput>;

/** Whether an rtk binary is installed on this host, independent of the toggle. */
export const rtkStatusOutput = z.object({
  available: z.boolean(),
  binaryPath: z.string().nullable(),
});

export type RtkStatus = z.infer<typeof rtkStatusOutput>;

// Set config option input (for Codex reasoning level, etc.)
export const setConfigOptionInput = z.object({
  sessionId: z.string(),
  configId: z.string(),
  value: z.string(),
});

// Subscribe to session events input
export const subscribeSessionInput = z.object({
  taskRunId: z.string(),
});

// Record activity input — resets the idle timeout for the given session
export const recordActivityInput = z.object({
  taskRunId: z.string(),
});

// Agent events
export const AgentServiceEvent = {
  SessionEvent: "session-event",
  PermissionRequest: "permission-request",
  SessionsIdle: "sessions-idle",
  SessionIdleKilled: "session-idle-killed",
  AgentFileActivity: "agent-file-activity",
  LlmActivity: "llm-activity",
} as const;

export interface AgentSessionEventPayload {
  taskRunId: string;
  payload: unknown;
}

export type PermissionOption = SdkPermissionOption;
export type PermissionRequestPayload = Omit<
  RequestPermissionRequest,
  "sessionId"
> & {
  taskRunId: string;
};

export interface SessionIdleKilledPayload {
  taskRunId: string;
  taskId: string;
}

export interface AgentFileActivityPayload {
  taskId: string;
  branchName: string | null;
}

export interface AgentServiceEvents {
  [AgentServiceEvent.SessionEvent]: AgentSessionEventPayload;
  [AgentServiceEvent.PermissionRequest]: PermissionRequestPayload;
  [AgentServiceEvent.SessionsIdle]: undefined;
  [AgentServiceEvent.SessionIdleKilled]: SessionIdleKilledPayload;
  [AgentServiceEvent.AgentFileActivity]: AgentFileActivityPayload;
  [AgentServiceEvent.LlmActivity]: undefined;
}

// Permission response input for tRPC
export const respondToPermissionInput = z.object({
  taskRunId: z.string(),
  toolCallId: z.string(),
  optionId: z.string(),
  // For "Other" option: custom text input from user (ACP extension via _meta)
  customInput: z.string().optional(),
  // For multi-question flows: all answers keyed by question text
  answers: z.record(z.string(), z.string()).optional(),
});

export type RespondToPermissionInput = z.infer<typeof respondToPermissionInput>;

// Permission cancellation input for tRPC
export const cancelPermissionInput = z.object({
  taskRunId: z.string(),
  toolCallId: z.string(),
});

export type CancelPermissionInput = z.infer<typeof cancelPermissionInput>;

export const listSessionsInput = z.object({
  taskId: z.string(),
});

export const detachedHeadContext = z.object({
  type: z.literal("detached_head"),
  branchName: z.string(),
  isDetached: z.boolean(),
});

export const sessionContextChangeSchema = detachedHeadContext;

export type SessionContextChange = z.infer<typeof sessionContextChangeSchema>;

export const notifySessionContextInput = z.object({
  sessionId: z.string(),
  context: sessionContextChangeSchema,
});

export type NotifySessionContextInput = z.infer<
  typeof notifySessionContextInput
>;

export const sessionInfoSchema = z.object({
  taskRunId: z.string(),
  repoPath: z.string(),
});

export const listSessionsOutput = z.array(sessionInfoSchema);

export const getGatewayModelsInput = z.object({
  apiHost: z.string(),
});

export const getGatewayModelsOutput = z.array(modelOptionSchema);

export const getPreviewConfigOptionsInput = z.object({
  apiHost: z.string(),
  adapter: z.enum(["claude", "codex"]),
});

export const getPreviewConfigOptionsOutput = z.array(sessionConfigOptionSchema);
