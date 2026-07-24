import type { UserRepositoryIntegrationRef } from "@posthog/core/integrations/repositories";
import type { Adapter, ExecutionMode, WorkspaceMode } from "@posthog/shared";
import {
  COLLAPSE_MODE_DEFAULT,
  type CollapseMode,
} from "@posthog/ui/features/sessions/components/new-thread/conversationThreadConfig";
import { electronStorage } from "@posthog/ui/shell/rendererStorage";
import { create } from "zustand";
import { persist } from "zustand/middleware";

// ---------- Types ----------

export type DefaultRunMode = "local" | "cloud" | "last_used";
export type LocalWorkspaceMode = "worktree" | "local";

export const DEFAULT_WORKSPACE_MODE: WorkspaceMode = "cloud";
export type AgentAdapter = Adapter;
export type DefaultInitialTaskMode = "plan" | "last_used";
export type DefaultMessagingMode = "queue" | "steer";
export type DefaultReasoningEffort =
  | "low"
  | "medium"
  | "high"
  | "xhigh"
  | "max"
  | "last_used";

export type SendMessagesWith = "enter" | "cmd+enter";
export type AutoConvertLongText = "off" | "1000" | "2500" | "5000" | "10000";
export type DiffOpenMode = "auto" | "split" | "same-pane" | "last-active-pane";

// When spoken notifications are allowed to talk, relative to what's on screen:
//   - always: speak regardless of what the user is looking at
//   - unviewed_task: stay quiet for the task currently on screen
//   - app_unfocused: only speak when PostHog isn't the focused app
// (needs-input lines ignore this so a blocker is never missed.)
export type SpokenFocusMode = "always" | "unviewed_task" | "app_unfocused";

export type BuiltInCompletionSound =
  | "none"
  | "guitar"
  | "danilo"
  | "revi"
  | "meep"
  | "meep-smol"
  | "bubbles"
  | "drop"
  | "knock"
  | "ring"
  | "shoot"
  | "slide"
  | "switch"
  | "wilhelm"
  | "icq"
  | "msn";

// A user-installed sound is selected by referencing its id as `custom:<id>`.
export type CompletionSound =
  | BuiltInCompletionSound
  | "random-all"
  | "random-custom"
  | `custom:${string}`;

// A notification sound the user recorded or imported. The clip is stored inline
// as a base64 data URL so it persists with the rest of the settings (no host
// filesystem dependency); a length cap on capture keeps that payload small.
export interface CustomSound {
  id: string;
  name: string;
  dataUrl: string;
  durationMs: number;
}

export type TerminalFont =
  | "berkeley-mono"
  | "jetbrains-mono"
  | "system"
  | "custom";

export interface HintState {
  count: number;
  learned: boolean;
}

/**
 * Snapshot of the user-level AGENTS.md/CLAUDE.md that personalization syncs
 * from. Runtime-only: the sync contribution re-reads the file on boot and
 * whenever the toggle flips on.
 */
export interface SyncedCustomInstructions {
  path: string;
  /** Home-relative form of `path` (e.g. `~/.claude/CLAUDE.md`), for display. */
  displayPath: string;
  content: string;
  truncated: boolean;
}

// ---------- Store shape ----------

interface SettingsStore {
  // Run mode + last-used flow defaults
  defaultRunMode: DefaultRunMode;
  lastUsedRunMode: "local" | "cloud";
  lastUsedLocalWorkspaceMode: LocalWorkspaceMode;
  lastUsedWorkspaceMode: WorkspaceMode;
  lastUsedAdapter: AgentAdapter;
  lastUsedModel: string | null;
  lastUsedReasoningEffort: string | null;
  lastUsedCloudRepository: string | null;
  cachedCloudRepositoryMap: Record<string, UserRepositoryIntegrationRef>;
  // Last-known default ("trunk") branch per cloud repo, keyed by lowercased
  // "owner/repo". Persisted so a cold start can pre-select trunk in the branch
  // picker immediately, before the (slow) live branch list resolves.
  cachedCloudDefaultBranchMap: Record<string, string>;
  lastUsedEnvironments: Record<string, string>;
  defaultInitialTaskMode: DefaultInitialTaskMode;
  lastUsedInitialTaskMode: ExecutionMode;
  // Mode last chosen when approving a plan; pre-selected on the next approval.
  lastPlanApprovalMode: ExecutionMode | null;
  defaultReasoningEffort: DefaultReasoningEffort;
  defaultMessagingMode: DefaultMessagingMode;
  setDefaultMessagingMode: (mode: DefaultMessagingMode) => void;
  setDefaultRunMode: (mode: DefaultRunMode) => void;
  setLastUsedRunMode: (mode: "local" | "cloud") => void;
  setLastUsedLocalWorkspaceMode: (mode: LocalWorkspaceMode) => void;
  setLastUsedWorkspaceMode: (mode: WorkspaceMode) => void;
  setLastUsedAdapter: (adapter: AgentAdapter) => void;
  setLastUsedModel: (model: string) => void;
  setLastUsedReasoningEffort: (effort: string) => void;
  setLastUsedCloudRepository: (repo: string | null) => void;
  setCachedCloudRepositoryMap: (
    map: Record<string, UserRepositoryIntegrationRef>,
  ) => void;
  setCachedCloudDefaultBranch: (repo: string, branch: string) => void;
  setLastUsedEnvironment: (
    repoPath: string,
    environmentId: string | null,
  ) => void;
  getLastUsedEnvironment: (repoPath: string) => string | null;
  setDefaultInitialTaskMode: (mode: DefaultInitialTaskMode) => void;
  setLastUsedInitialTaskMode: (mode: ExecutionMode) => void;
  setLastPlanApprovalMode: (mode: ExecutionMode) => void;
  setDefaultReasoningEffort: (effort: DefaultReasoningEffort) => void;

  // Notifications
  desktopNotifications: boolean;
  dockBadgeNotifications: boolean;
  dockBounceNotifications: boolean;
  toastNotifications: boolean;
  completionSound: CompletionSound;
  completionVolume: number;
  scaleSoundWithTaskLength: boolean;
  customSounds: CustomSound[];
  setDesktopNotifications: (enabled: boolean) => void;
  setDockBadgeNotifications: (enabled: boolean) => void;
  setDockBounceNotifications: (enabled: boolean) => void;
  setToastNotifications: (enabled: boolean) => void;
  setCompletionSound: (sound: CompletionSound) => void;
  setCompletionVolume: (volume: number) => void;
  setScaleSoundWithTaskLength: (enabled: boolean) => void;
  addCustomSound: (sound: CustomSound) => void;
  removeCustomSound: (id: string) => void;
  renameCustomSound: (id: string, name: string) => void;

  // Spoken notifications
  spokenNotifications: boolean;
  spokenNotifyNeedsInput: boolean;
  spokenNotifyCompletion: boolean;
  spokenNotifyProgress: boolean;
  spokenFocusMode: SpokenFocusMode;
  elevenLabsVoiceId: string;
  // Mirrors whether an ElevenLabs key is stored (the key itself lives in
  // encrypted secure storage, never in this persisted blob).
  elevenLabsKeyConfigured: boolean;
  setSpokenNotifications: (enabled: boolean) => void;
  setSpokenNotifyNeedsInput: (enabled: boolean) => void;
  setSpokenNotifyCompletion: (enabled: boolean) => void;
  setSpokenNotifyProgress: (enabled: boolean) => void;
  setSpokenFocusMode: (mode: SpokenFocusMode) => void;
  setElevenLabsVoiceId: (voiceId: string) => void;
  setElevenLabsKeyConfigured: (configured: boolean) => void;

  // Composer / chat
  autoConvertLongText: AutoConvertLongText;
  sendMessagesWith: SendMessagesWith;
  customInstructions: string;
  // When on, personalization mirrors the user-level AGENTS.md (or CLAUDE.md)
  // instead of the hand-typed customInstructions above.
  syncCustomInstructionsFromFile: boolean;
  syncedCustomInstructions: SyncedCustomInstructions | null;
  setAutoConvertLongText: (value: AutoConvertLongText) => void;
  setSendMessagesWith: (mode: SendMessagesWith) => void;
  setCustomInstructions: (instructions: string) => void;
  setSyncCustomInstructionsFromFile: (enabled: boolean) => void;
  setSyncedCustomInstructions: (
    synced: SyncedCustomInstructions | null,
  ) => void;

  // Diff viewer
  diffOpenMode: DiffOpenMode;
  setDiffOpenMode: (mode: DiffOpenMode) => void;

  // System / power / permissions
  allowBypassPermissions: boolean;
  preventSleepWhileRunning: boolean;
  debugLogsCloudRuns: boolean;
  // When on, cloud runs push their work and open a draft PR on completion
  // without waiting for an explicit ask.
  autoPublishCloudRuns: boolean;
  // When on, agent runs compress eligible command output through rtk before it
  // reaches the model. Split by modality: local covers local and worktree
  // sessions, cloud covers cloud runs.
  rtkEnabledLocal: boolean;
  rtkEnabledCloud: boolean;
  setAllowBypassPermissions: (enabled: boolean) => void;
  setPreventSleepWhileRunning: (enabled: boolean) => void;
  setDebugLogsCloudRuns: (enabled: boolean) => void;
  setAutoPublishCloudRuns: (enabled: boolean) => void;
  setRtkEnabledLocal: (enabled: boolean) => void;
  setRtkEnabledCloud: (enabled: boolean) => void;

  // Terminal
  terminalFont: TerminalFont;
  terminalCustomFontFamily: string;
  terminalGpuRendering: boolean;
  setTerminalFont: (font: TerminalFont) => void;
  setTerminalCustomFontFamily: (value: string) => void;
  setTerminalGpuRendering: (enabled: boolean) => void;

  // Conversation thread (new-thread)
  conversationCollapseMode: CollapseMode;
  setConversationCollapseMode: (mode: CollapseMode) => void;

  // Sidebar
  // Shows a per-repo "Worktrees" dropdown of task-less worktrees a click can
  // start a task in. Opt-in: off by default to keep the sidebar uncluttered.
  showSidebarWorktrees: boolean;
  setShowSidebarWorktrees: (enabled: boolean) => void;

  // Experimental / misc
  hedgehogMode: boolean;
  slotMachineMode: boolean;
  brainrotMode: boolean;
  mcpAppsDisabledServers: string[];
  downloadUpdatesAutomatically: boolean;
  dismissibleUpdateBanners: boolean;
  lastSeenChangelogVersion: string | null;
  // Renders the conversation with the new ChatX (quill) primitives instead of
  // the virtualized ConversationView. Local A/B toggle while the rebuild bakes.
  useNewChatThread: boolean;
  setUseNewChatThread: (enabled: boolean) => void;
  setHedgehogMode: (enabled: boolean) => void;
  setSlotMachineMode: (enabled: boolean) => void;
  setBrainrotMode: (enabled: boolean) => void;
  setMcpAppsDisabledServers: (servers: string[]) => void;
  setDownloadUpdatesAutomatically: (enabled: boolean) => void;
  setDismissibleUpdateBanners: (enabled: boolean) => void;
  setLastSeenChangelogVersion: (version: string | null) => void;

  // Onboarding hints
  hints: Record<string, HintState>;
  shouldShowHint: (key: string, max?: number) => boolean;
  recordHintShown: (key: string) => void;
  markHintLearned: (key: string) => void;

  _hasHydrated: boolean;
  setHasHydrated: (hydrated: boolean) => void;
}

// ---------- Store ----------

// Single source of truth for notification setting defaults — used both as the
// store's initial values and by the Notifications settings "Reset to defaults".
export const NOTIFICATION_DEFAULTS = {
  desktopNotifications: true,
  dockBadgeNotifications: true,
  dockBounceNotifications: false,
  toastNotifications: true,
  completionSound: "none" as CompletionSound,
  completionVolume: 80,
  scaleSoundWithTaskLength: false,
  spokenNotifications: false,
  spokenNotifyNeedsInput: true,
  spokenNotifyCompletion: true,
  spokenNotifyProgress: false,
  spokenFocusMode: "unviewed_task" as SpokenFocusMode,
  elevenLabsVoiceId: "",
  elevenLabsKeyConfigured: false,
};

export const useSettingsStore = create<SettingsStore>()(
  persist(
    (set, get) => ({
      // Run mode + last-used flow defaults
      defaultRunMode: "last_used",
      lastUsedRunMode: "local",
      lastUsedLocalWorkspaceMode: "local",
      lastUsedWorkspaceMode: DEFAULT_WORKSPACE_MODE,
      lastUsedAdapter: "claude",
      lastUsedModel: null,
      lastUsedReasoningEffort: null,
      lastUsedCloudRepository: null,
      cachedCloudRepositoryMap: {},
      cachedCloudDefaultBranchMap: {},
      lastUsedEnvironments: {},
      defaultInitialTaskMode: "plan",
      lastUsedInitialTaskMode: "plan",
      lastPlanApprovalMode: null,
      defaultReasoningEffort: "last_used",
      defaultMessagingMode: "queue",
      setDefaultRunMode: (mode) => set({ defaultRunMode: mode }),
      setLastUsedRunMode: (mode) => set({ lastUsedRunMode: mode }),
      setLastUsedLocalWorkspaceMode: (mode) =>
        set({ lastUsedLocalWorkspaceMode: mode }),
      setLastUsedWorkspaceMode: (mode) => set({ lastUsedWorkspaceMode: mode }),
      setLastUsedAdapter: (adapter) => set({ lastUsedAdapter: adapter }),
      setLastUsedModel: (model) => set({ lastUsedModel: model }),
      setLastUsedReasoningEffort: (effort) =>
        set({ lastUsedReasoningEffort: effort }),
      setLastUsedCloudRepository: (repo) =>
        set({ lastUsedCloudRepository: repo }),
      setCachedCloudRepositoryMap: (map) =>
        set({ cachedCloudRepositoryMap: map }),
      setCachedCloudDefaultBranch: (repo, branch) =>
        set((state) => {
          if (state.cachedCloudDefaultBranchMap[repo] === branch) return {};
          return {
            cachedCloudDefaultBranchMap: {
              ...state.cachedCloudDefaultBranchMap,
              [repo]: branch,
            },
          };
        }),
      setLastUsedEnvironment: (repoPath, environmentId) =>
        set((state) => {
          const next = { ...state.lastUsedEnvironments };
          if (environmentId) {
            next[repoPath] = environmentId;
          } else {
            delete next[repoPath];
          }
          return { lastUsedEnvironments: next };
        }),
      getLastUsedEnvironment: (repoPath) =>
        get().lastUsedEnvironments[repoPath] ?? null,
      setDefaultInitialTaskMode: (mode) =>
        set({ defaultInitialTaskMode: mode }),
      setLastUsedInitialTaskMode: (mode) =>
        set({ lastUsedInitialTaskMode: mode }),
      setLastPlanApprovalMode: (mode) => set({ lastPlanApprovalMode: mode }),
      setDefaultReasoningEffort: (effort) =>
        set({ defaultReasoningEffort: effort }),
      setDefaultMessagingMode: (mode) => set({ defaultMessagingMode: mode }),

      // Notifications
      ...NOTIFICATION_DEFAULTS,
      // Kept out of NOTIFICATION_DEFAULTS so "Reset to defaults" never discards
      // sounds the user installed.
      customSounds: [],
      setDesktopNotifications: (enabled) =>
        set({ desktopNotifications: enabled }),
      setDockBadgeNotifications: (enabled) =>
        set({ dockBadgeNotifications: enabled }),
      setDockBounceNotifications: (enabled) =>
        set({ dockBounceNotifications: enabled }),
      setToastNotifications: (enabled) => set({ toastNotifications: enabled }),
      setCompletionSound: (sound) => set({ completionSound: sound }),
      setCompletionVolume: (volume) => set({ completionVolume: volume }),
      setSpokenNotifications: (enabled) =>
        set({ spokenNotifications: enabled }),
      setSpokenNotifyNeedsInput: (enabled) =>
        set({ spokenNotifyNeedsInput: enabled }),
      setSpokenNotifyCompletion: (enabled) =>
        set({ spokenNotifyCompletion: enabled }),
      setSpokenNotifyProgress: (enabled) =>
        set({ spokenNotifyProgress: enabled }),
      setSpokenFocusMode: (mode) => set({ spokenFocusMode: mode }),
      setElevenLabsVoiceId: (voiceId) => set({ elevenLabsVoiceId: voiceId }),
      setElevenLabsKeyConfigured: (configured) =>
        set({ elevenLabsKeyConfigured: configured }),
      setScaleSoundWithTaskLength: (enabled) =>
        set({ scaleSoundWithTaskLength: enabled }),
      addCustomSound: (sound) =>
        set((state) => ({ customSounds: [...state.customSounds, sound] })),
      removeCustomSound: (id) =>
        set((state) => {
          const customSounds = state.customSounds.filter((s) => s.id !== id);
          const soundNowUnplayable =
            state.completionSound === `custom:${id}` ||
            (state.completionSound === "random-custom" &&
              customSounds.length === 0);
          return {
            customSounds,
            completionSound: soundNowUnplayable
              ? "none"
              : state.completionSound,
          };
        }),
      renameCustomSound: (id, name) =>
        set((state) => ({
          customSounds: state.customSounds.map((s) =>
            s.id === id ? { ...s, name } : s,
          ),
        })),

      // Composer / chat
      autoConvertLongText: "2500",
      sendMessagesWith: "enter",
      customInstructions: "",
      syncCustomInstructionsFromFile: false,
      syncedCustomInstructions: null,
      setAutoConvertLongText: (value) => set({ autoConvertLongText: value }),
      setSendMessagesWith: (mode) => set({ sendMessagesWith: mode }),
      setCustomInstructions: (instructions) =>
        set({ customInstructions: instructions }),
      setSyncCustomInstructionsFromFile: (enabled) =>
        set({ syncCustomInstructionsFromFile: enabled }),
      setSyncedCustomInstructions: (synced) =>
        set({ syncedCustomInstructions: synced }),

      // Diff viewer
      diffOpenMode: "auto",
      setDiffOpenMode: (mode) => set({ diffOpenMode: mode }),

      // System / power / permissions
      allowBypassPermissions: false,
      preventSleepWhileRunning: false,
      debugLogsCloudRuns: false,
      autoPublishCloudRuns: true,
      rtkEnabledLocal: true,
      rtkEnabledCloud: true,
      setAllowBypassPermissions: (enabled) =>
        set({ allowBypassPermissions: enabled }),
      setPreventSleepWhileRunning: (enabled) =>
        set({ preventSleepWhileRunning: enabled }),
      setDebugLogsCloudRuns: (enabled) => set({ debugLogsCloudRuns: enabled }),
      setAutoPublishCloudRuns: (enabled) =>
        set({ autoPublishCloudRuns: enabled }),
      setRtkEnabledLocal: (enabled) => set({ rtkEnabledLocal: enabled }),
      setRtkEnabledCloud: (enabled) => set({ rtkEnabledCloud: enabled }),

      // Terminal
      terminalFont: "berkeley-mono",
      terminalCustomFontFamily: "",
      terminalGpuRendering: true,
      setTerminalFont: (font) => set({ terminalFont: font }),
      setTerminalCustomFontFamily: (value) =>
        set({ terminalCustomFontFamily: value }),
      setTerminalGpuRendering: (enabled) =>
        set({ terminalGpuRendering: enabled }),

      // Conversation thread (new-thread)
      conversationCollapseMode: COLLAPSE_MODE_DEFAULT,
      setConversationCollapseMode: (mode) =>
        set({ conversationCollapseMode: mode }),

      // Sidebar
      showSidebarWorktrees: false,
      setShowSidebarWorktrees: (enabled) =>
        set({ showSidebarWorktrees: enabled }),

      // Experimental / misc
      hedgehogMode: false,
      slotMachineMode: false,
      brainrotMode: false,
      mcpAppsDisabledServers: [],
      downloadUpdatesAutomatically: true,
      dismissibleUpdateBanners: false,
      lastSeenChangelogVersion: null,
      useNewChatThread: false,
      setUseNewChatThread: (enabled) => set({ useNewChatThread: enabled }),
      setHedgehogMode: (enabled) => set({ hedgehogMode: enabled }),
      setSlotMachineMode: (enabled) => set({ slotMachineMode: enabled }),
      setBrainrotMode: (enabled) => set({ brainrotMode: enabled }),
      setDownloadUpdatesAutomatically: (enabled) =>
        set({ downloadUpdatesAutomatically: enabled }),
      setDismissibleUpdateBanners: (enabled) =>
        set({ dismissibleUpdateBanners: enabled }),
      setLastSeenChangelogVersion: (version) =>
        set({ lastSeenChangelogVersion: version }),
      setMcpAppsDisabledServers: (servers) =>
        set({ mcpAppsDisabledServers: servers }),

      // Onboarding hints
      hints: {},
      shouldShowHint: (key, max = 3) => {
        const hint = get().hints[key];
        if (!hint) return true;
        return !hint.learned && hint.count < max;
      },
      recordHintShown: (key) =>
        set((state) => {
          const current = state.hints[key] ?? { count: 0, learned: false };
          return {
            hints: {
              ...state.hints,
              [key]: { ...current, count: current.count + 1 },
            },
          };
        }),
      markHintLearned: (key) =>
        set((state) => {
          const current = state.hints[key] ?? { count: 0, learned: false };
          return {
            hints: {
              ...state.hints,
              [key]: { ...current, learned: true },
            },
          };
        }),

      _hasHydrated: false,
      setHasHydrated: (hydrated) => set({ _hasHydrated: hydrated }),
    }),
    {
      name: "settings-storage",
      storage: electronStorage,
      partialize: (state) => ({
        // Run mode + last-used flow defaults
        defaultRunMode: state.defaultRunMode,
        lastUsedRunMode: state.lastUsedRunMode,
        lastUsedLocalWorkspaceMode: state.lastUsedLocalWorkspaceMode,
        lastUsedWorkspaceMode: state.lastUsedWorkspaceMode,
        lastUsedAdapter: state.lastUsedAdapter,
        lastUsedModel: state.lastUsedModel,
        lastUsedReasoningEffort: state.lastUsedReasoningEffort,
        lastUsedCloudRepository: state.lastUsedCloudRepository,
        cachedCloudRepositoryMap: state.cachedCloudRepositoryMap,
        cachedCloudDefaultBranchMap: state.cachedCloudDefaultBranchMap,
        lastUsedEnvironments: state.lastUsedEnvironments,
        defaultInitialTaskMode: state.defaultInitialTaskMode,
        lastUsedInitialTaskMode: state.lastUsedInitialTaskMode,
        lastPlanApprovalMode: state.lastPlanApprovalMode,
        defaultReasoningEffort: state.defaultReasoningEffort,
        defaultMessagingMode: state.defaultMessagingMode,

        // Notifications
        desktopNotifications: state.desktopNotifications,
        dockBadgeNotifications: state.dockBadgeNotifications,
        dockBounceNotifications: state.dockBounceNotifications,
        toastNotifications: state.toastNotifications,
        completionSound: state.completionSound,
        completionVolume: state.completionVolume,
        scaleSoundWithTaskLength: state.scaleSoundWithTaskLength,
        customSounds: state.customSounds,
        spokenNotifications: state.spokenNotifications,
        spokenNotifyNeedsInput: state.spokenNotifyNeedsInput,
        spokenNotifyCompletion: state.spokenNotifyCompletion,
        spokenNotifyProgress: state.spokenNotifyProgress,
        spokenFocusMode: state.spokenFocusMode,
        elevenLabsVoiceId: state.elevenLabsVoiceId,
        elevenLabsKeyConfigured: state.elevenLabsKeyConfigured,

        // Composer / chat
        autoConvertLongText: state.autoConvertLongText,
        sendMessagesWith: state.sendMessagesWith,
        customInstructions: state.customInstructions,
        syncCustomInstructionsFromFile: state.syncCustomInstructionsFromFile,

        // Diff viewer
        diffOpenMode: state.diffOpenMode,

        // System / power / permissions
        allowBypassPermissions: state.allowBypassPermissions,
        preventSleepWhileRunning: state.preventSleepWhileRunning,
        debugLogsCloudRuns: state.debugLogsCloudRuns,
        autoPublishCloudRuns: state.autoPublishCloudRuns,
        rtkEnabledLocal: state.rtkEnabledLocal,
        rtkEnabledCloud: state.rtkEnabledCloud,

        // Terminal
        terminalFont: state.terminalFont,
        terminalCustomFontFamily: state.terminalCustomFontFamily,
        terminalGpuRendering: state.terminalGpuRendering,

        // Conversation thread (new-thread)
        conversationCollapseMode: state.conversationCollapseMode,

        // Sidebar
        showSidebarWorktrees: state.showSidebarWorktrees,

        // Experimental / misc
        hedgehogMode: state.hedgehogMode,
        slotMachineMode: state.slotMachineMode,
        brainrotMode: state.brainrotMode,
        mcpAppsDisabledServers: state.mcpAppsDisabledServers,
        downloadUpdatesAutomatically: state.downloadUpdatesAutomatically,
        dismissibleUpdateBanners: state.dismissibleUpdateBanners,
        lastSeenChangelogVersion: state.lastSeenChangelogVersion,
        useNewChatThread: state.useNewChatThread,

        // Onboarding hints
        hints: state.hints,
      }),
      onRehydrateStorage: () => (state) => {
        state?.setHasHydrated(true);
      },
      merge: (persisted, current) => {
        const merged = {
          ...current,
          ...(persisted as Partial<SettingsStore>),
        };
        if (typeof merged.autoConvertLongText === "boolean") {
          (merged as Record<string, unknown>).autoConvertLongText =
            merged.autoConvertLongText ? "1000" : "off";
        }
        if ((merged.autoConvertLongText as string) === "500") {
          (merged as Record<string, unknown>).autoConvertLongText = "1000";
        }
        if (
          merged.completionSound === "random-custom" &&
          (!merged.customSounds || merged.customSounds.length === 0)
        ) {
          (merged as Record<string, unknown>).completionSound = "none";
        }
        return merged;
      },
    },
  ),
);

/**
 * The personalization to inject into sessions. Strictly either/or: while file
 * sync is on, only the synced AGENTS.md/CLAUDE.md snapshot applies (empty when
 * no file was found) and the hand-typed custom instructions are ignored.
 */
export function getEffectiveCustomInstructions(
  state: Pick<
    SettingsStore,
    | "customInstructions"
    | "syncCustomInstructionsFromFile"
    | "syncedCustomInstructions"
  >,
): string {
  if (state.syncCustomInstructionsFromFile) {
    const content = state.syncedCustomInstructions?.content ?? "";
    return content.trim() ? content : "";
  }
  return state.customInstructions;
}

/**
 * The repository a one-click cloud task should default to: the last-used cloud
 * repository when it's still connected, otherwise the first connected one.
 * `repositories` is expected to be normalized (lowercased) already.
 */
export function resolveDefaultCloudRepository(
  repositories: string[],
  lastUsedCloudRepository: string | null,
): string | null {
  const normalizedLastUsed = lastUsedCloudRepository?.toLowerCase() ?? null;
  if (normalizedLastUsed && repositories.includes(normalizedLastUsed)) {
    return normalizedLastUsed;
  }
  return repositories[0] ?? null;
}
