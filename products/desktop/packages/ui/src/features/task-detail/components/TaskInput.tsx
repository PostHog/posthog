import { FileText, X } from "@phosphor-icons/react";
import type { AutoresearchService } from "@posthog/core/autoresearch/autoresearch";
import { AUTORESEARCH_SERVICE } from "@posthog/core/autoresearch/identifiers";
import { buildKickoffPreamble } from "@posthog/core/autoresearch/prompts";
import { buildFileLineReferencePrompt } from "@posthog/core/code-review/reviewPrompts";
import type { EditorContent } from "@posthog/core/message-editor/content";
import { xmlToContent } from "@posthog/core/message-editor/content";
import { isValidConfigValue } from "@posthog/core/task-detail/configOptions";
import { useServiceOptional } from "@posthog/di/react";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { ButtonGroup } from "@posthog/quill";
import { type AgentRuntime, ANALYTICS_EVENTS } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { openSettings } from "@posthog/ui/features/settings/hooks/useOpenSettings";
import type { TaskInputReportAssociation } from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import { useTaskInputPrefillStore } from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import { navigateToInbox } from "@posthog/ui/router/navigationBridge";
import { useAppView } from "@posthog/ui/router/useAppView";
import { track } from "@posthog/ui/shell/analytics";
import { Box, Flex, Text, Tooltip } from "@radix-ui/themes";
import { useQuery } from "@tanstack/react-query";
import { AnimatePresence, motion } from "framer-motion";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useConnectivity } from "../../../hooks/useConnectivity";
import { DotPatternBackground } from "../../../primitives/DotPatternBackground";
import { toast } from "../../../primitives/toast";
import { useActiveRepoStore } from "../../../shell/activeRepoStore";
import { useHostCapabilities } from "../../../shell/useHostCapabilities";
import { FOCUSABLE_SELECTOR } from "../../../utils/overlay";
import { useAuthStateValue } from "../../auth/store";
import { AutoresearchComposerControls } from "../../autoresearch/AutoresearchComposerControls";
import {
  autoresearchPendingRun,
  useAutoresearchDraftStore,
} from "../../autoresearch/autoresearchDraftStore";
import { toStageSelectOptions } from "../../autoresearch/stageModels";
import { useAutoresearchEnabled } from "../../autoresearch/useAutoresearchEnabled";
import { useFileSearchStore } from "../../command/fileSearchStore";
import { NewTaskFilePreview } from "../../command/NewTaskFilePreview";
import { EnvironmentSelector } from "../../environments/EnvironmentSelector";
import { useFeatureFlag } from "../../feature-flags/useFeatureFlag";
import { useFeatureFlagsLoaded } from "../../feature-flags/useFeatureFlagsLoaded";
import { AdditionalDirectoriesButton } from "../../folder-picker/AdditionalDirectoriesButton";
import { FolderPicker } from "../../folder-picker/FolderPicker";
import { GitHubRepoPicker } from "../../folder-picker/GitHubRepoPicker";
import { useFolders } from "../../folders/useFolders";
import { BranchSelector } from "../../git-interaction/components/BranchSelector";
import { GitBranchDialog } from "../../git-interaction/components/GitInteractionDialogs";
import { useGitInteractionStore } from "../../git-interaction/state/gitInteractionStore";
import { useGitQueries } from "../../git-interaction/useGitQueries";
import {
  createBranch,
  getBranchNameInputState,
} from "../../git-interaction/utils/branchCreation";
import { useInboxReportSelectionStore } from "../../inbox/stores/inboxReportSelectionStore";
import { useIntegrationSelectors } from "../../integrations/store";
import {
  useUserGithubBranches,
  useUserGithubRepositories,
  useUserRepositoryIntegration,
} from "../../integrations/useIntegrations";
import { skillToEditorCommand } from "../../message-editor/commands";
import { PromptHistoryDialog } from "../../message-editor/components/PromptHistoryDialog";
import { PromptInput } from "../../message-editor/components/PromptInput";
import { contentToXml } from "../../message-editor/content";
import { useDraftStore } from "../../message-editor/draftStore";
import { useTaskInputHistoryStore } from "../../message-editor/taskInputHistoryStore";
import type { EditorHandle } from "../../message-editor/types";
import { useAutoFocusOnTyping } from "../../message-editor/useAutoFocusOnTyping";
import { resolveAndAttachDroppedFiles } from "../../message-editor/utils/persistFile";
import { usePanelLayoutStore } from "../../panels/panelLayoutStore";
import { DropZoneOverlay } from "../../sessions/components/DropZoneOverlay";
import { ReasoningLevelSelector } from "../../sessions/components/ReasoningLevelSelector";
import { UnifiedModelSelector } from "../../sessions/components/UnifiedModelSelector";
import { getCurrentModeFromConfigOptions } from "../../sessions/sessionStore";
import {
  type AgentAdapter,
  DEFAULT_WORKSPACE_MODE,
  useSettingsStore,
} from "../../settings/settingsStore";
import { useSkills } from "../../skills/useSkills";
import { useCloudModeEnabled } from "../hooks/useCloudModeEnabled";
import {
  areReposReady,
  useInitialRepoSelectionFromFolderId,
} from "../hooks/useInitialRepoSelectionFromFolderId";
import { usePreviewConfig } from "../hooks/usePreviewConfig";
import { useTaskCreation } from "../hooks/useTaskCreation";
import { useWarmTask } from "../hooks/useWarmTask";
import { resolveWorkspaceModePreference } from "../hooks/workspaceModePreference";
import { AgentRuntimeSelect } from "./AgentRuntimeSelect";
import { CloudGithubMissingNotice } from "./CloudGithubMissingNotice";
import { NewTaskSuggestions } from "./ContinueCliSessions";
import {
  type SuggestedPrompt,
  SuggestedPromptCard,
} from "./SuggestedPromptCard";
import { type WorkspaceMode, WorkspaceModeSelect } from "./WorkspaceModeSelect";

interface TaskInputProps {
  sessionId?: string;
  onTaskCreated?: (task: Task) => void;
  initialPrompt?: string;
  initialPromptKey?: string;
  initialCloudRepository?: string;
  initialModel?: string;
  initialMode?: string;
  reportAssociation?: TaskInputReportAssociation;
  /** Optional channel CONTEXT.md, appended to the initial prompt as background. */
  channelContext?: string;
  /** Display name of the channel the CONTEXT.md came from (for the chip). */
  channelName?: string;
  /**
   * Desktop file-system folder id that owns the channel's CONTEXT.md. When set,
   * the injected context lets the agent publish upkeep corrections addressed to
   * this id rather than resolving the channel by name.
   */
  channelContextId?: string;
  /**
   * Channels "generic chat box" mode: hide the repo/branch pickers and let the
   * task be submitted without a repo. The agent decides at runtime whether it
   * needs a repo and attaches one lazily.
   */
  allowNoRepo?: boolean;
  /**
   * Channels new-task starter prompts. When provided, a column of suggestion
   * cards renders below the input while it's empty; clicking one fills the
   * composer. Channels-only — omitted on the /code new-task screen.
   */
  suggestions?: SuggestedPrompt[];
  /**
   * Called when a starter-prompt suggestion card is clicked, with the card's
   * label. Optional analytics hook for the channels new-task screen; has no
   * effect on the fill behaviour.
   */
  onSuggestionSelect?: (label: string) => void;
  /**
   * Called when the channel CONTEXT.md chip is clicked (not its dismiss × ).
   * When provided, the chip's icon+label becomes a button — the channels
   * new-task screen uses it to open the CONTEXT.md in a side panel. Without it
   * the chip is non-interactive (only dismissable).
   */
  onContextChipClick?: () => void;
}

export function TaskInput({
  sessionId = "task-input",
  onTaskCreated,
  initialPrompt,
  initialPromptKey,
  initialCloudRepository,
  initialModel,
  initialMode,
  reportAssociation,
  channelContext,
  channelName,
  channelContextId,
  allowNoRepo,
  suggestions,
  onSuggestionSelect,
  onContextChipClick,
}: TaskInputProps = {}) {
  const cloudRegion = useAuthStateValue((s) => s.cloudRegion);
  const trpc = useHostTRPC();
  const hostClient = useHostTRPCClient();
  const gitWriteClient = useMemo(
    () => ({
      createBranch: async (directoryPath: string, branchName: string) => {
        await hostClient.git.createBranch.mutate({ directoryPath, branchName });
      },
    }),
    [hostClient],
  );
  const view = useAppView();
  const clearTaskInputReportAssociation = useTaskInputPrefillStore(
    (s) => s.clearReportAssociation,
  );
  const setSelectedReportIds = useInboxReportSelectionStore(
    (s) => s.setSelectedReportIds,
  );
  const selectedDirectory = useActiveRepoStore((s) => s.path);
  const setSelectedDirectory = useActiveRepoStore((s) => s.setPath);
  // Inline file preview opened from the command palette's file search.
  const previewFile = useFileSearchStore((s) => s.previewFile);
  const closePreviewFile = useFileSearchStore((s) => s.closePreview);
  // Clear the open file on repo change + unmount.
  // biome-ignore lint/correctness/useExhaustiveDependencies: clear on repo change + unmount only
  useEffect(() => closePreviewFile, [selectedDirectory, closePreviewFile]);
  const { data: mostRecentRepo } = useQuery(
    trpc.folders.getMostRecentlyAccessedRepository.queryOptions(),
  );
  const {
    setLastUsedLocalWorkspaceMode,
    lastUsedLocalWorkspaceMode,
    lastUsedWorkspaceMode,
    setLastUsedWorkspaceMode,
    lastUsedAdapter,
    setLastUsedAdapter,
    lastUsedCloudRepository,
    setLastUsedCloudRepository,
    cachedCloudDefaultBranchMap,
    setCachedCloudDefaultBranch,
    allowBypassPermissions,
    setLastUsedEnvironment,
    getLastUsedEnvironment,
    defaultInitialTaskMode,
    lastUsedInitialTaskMode,
    setLastUsedReasoningEffort,
    setLastUsedModel,
    _hasHydrated: settingsHydrated,
  } = useSettingsStore();
  const { data: skills } = useSkills();

  const editorRef = useRef<EditorHandle>(null);
  const handleAddSelectionToPrompt = useCallback(
    (startLine: number, endLine: number, text: string) => {
      if (!selectedDirectory || !previewFile) return;
      const absolutePath = `${selectedDirectory.replace(/\/+$/, "")}/${previewFile}`;
      const prompt = buildFileLineReferencePrompt(
        absolutePath,
        startLine,
        endLine,
        text,
      );
      editorRef.current?.insertEditorContent(xmlToContent(prompt));
      editorRef.current?.focus();
    },
    [selectedDirectory, previewFile],
  );
  const containerRef = useRef<HTMLDivElement>(null);
  const buttonGroupRef = useRef<HTMLDivElement>(null);
  const dragCounterRef = useRef(0);
  const reportInputHadContentRef = useRef(false);

  const [editorIsEmpty, setEditorIsEmpty] = useState(true);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [isCreatingBranch, setIsCreatingBranch] = useState(false);
  const [selectedBranch, setSelectedBranch] = useState<string | null>(null);
  const [runtime, setRuntime] = useState<AgentRuntime>("acp");
  const [cloudRepoSearchQuery, setCloudRepoSearchQuery] = useState("");
  const [isCloudRepoPickerOpen, setIsCloudRepoPickerOpen] = useState(false);
  const [cloudBranchSearchQuery, setCloudBranchSearchQuery] = useState("");
  const [selectedEnvironment, setSelectedEnvironmentRaw] = useState<
    string | null
  >(null);
  const [selectedCloudEnvId, setSelectedCloudEnvId] = useState<string | null>(
    null,
  );
  const [selectedCustomImageId, setSelectedCustomImageId] = useState<
    string | null
  >(null);
  const [activeReportAssociation, setActiveReportAssociation] = useState(
    reportAssociation ?? null,
  );

  // Channel CONTEXT.md is included by default; the chip lets the user drop it
  // from this task's prompt. Re-include whenever the source context changes
  // (e.g. switching channels) so a dismissal doesn't stick across channels.
  const [channelContextDismissed, setChannelContextDismissed] = useState(false);
  const lastChannelContextRef = useRef(channelContext);
  useEffect(() => {
    if (lastChannelContextRef.current !== channelContext) {
      lastChannelContextRef.current = channelContext;
      setChannelContextDismissed(false);
    }
  }, [channelContext]);
  const includeChannelContext = !!channelContext && !channelContextDismissed;

  const adapter = lastUsedAdapter;
  const prefillRequestKey = initialPromptKey ?? initialPrompt;

  useEffect(() => {
    if (!initialPrompt || !prefillRequestKey) return;
    useDraftStore.getState().actions.setPendingContent(sessionId, {
      segments: [{ type: "text", text: initialPrompt }],
    });
  }, [initialPrompt, prefillRequestKey, sessionId]);

  useEffect(() => {
    reportInputHadContentRef.current = false;
    setActiveReportAssociation(reportAssociation ?? null);
  }, [reportAssociation]);

  const handleDismissReportAssociation = useCallback(() => {
    reportInputHadContentRef.current = false;
    setActiveReportAssociation(null);
    clearTaskInputReportAssociation();
  }, [clearTaskInputReportAssociation]);

  const handleEditorEmptyChange = useCallback(
    (isEmpty: boolean) => {
      setEditorIsEmpty(isEmpty);

      if (!activeReportAssociation) return;
      if (!isEmpty) {
        reportInputHadContentRef.current = true;
        return;
      }
      if (!reportInputHadContentRef.current) return;

      reportInputHadContentRef.current = false;
      setActiveReportAssociation(null);
      clearTaskInputReportAssociation();
    },
    [activeReportAssociation, clearTaskInputReportAssociation],
  );

  const handleOpenAssociatedReport = useCallback(() => {
    if (!activeReportAssociation) return;
    navigateToInbox();
    setSelectedReportIds([activeReportAssociation.reportId]);
  }, [activeReportAssociation, setSelectedReportIds]);

  useEffect(() => {
    if (!selectedDirectory && mostRecentRepo?.path) {
      setSelectedDirectory(mostRecentRepo.path);
    }
  }, [mostRecentRepo?.path, selectedDirectory, setSelectedDirectory]);

  const setAdapter = (newAdapter: AgentAdapter) =>
    setLastUsedAdapter(newAdapter);

  const {
    repositories,
    getInstallationIdForRepo,
    getUserIntegrationIdForRepo,
    isLoadingRepos,
    isRefreshingRepos,
    refreshRepositories,
    hasGithubIntegration,
  } = useUserRepositoryIntegration();

  // Force cloud mode on cloud-only hosts (web).
  const { localWorkspaces } = useHostCapabilities();
  const cloudModeEnabled = useCloudModeEnabled();
  const piHarnessEnabled = useFeatureFlag("pi-harness");
  const flagsLoaded = useFeatureFlagsLoaded();
  const reposReady = areReposReady({
    isLoadingRepos,
    repositoriesCount: repositories.length,
    hasGithubIntegration,
  });

  const [workspaceMode, setWorkspaceModeState] = useState<WorkspaceMode>(() => {
    if (initialCloudRepository) return "cloud";
    if (!localWorkspaces) return "cloud";
    return resolveWorkspaceModePreference({
      preferredMode: lastUsedWorkspaceMode || DEFAULT_WORKSPACE_MODE,
      cloudModeEnabled,
      hasGithubIntegration,
      lastUsedLocalWorkspaceMode,
    });
  });

  // A positive flag or integration signal is final, but a negative one may
  // just mean the async flag fetch or integrations query hasn't landed yet, so
  // a cloud preference only resolves once each negative signal is settled.
  const cloudSignalsSettled =
    (cloudModeEnabled || flagsLoaded) &&
    (hasGithubIntegration || !isLoadingRepos);

  const didResolveWorkspaceModeRef = useRef(false);
  useEffect(() => {
    if (didResolveWorkspaceModeRef.current) return;
    if (!settingsHydrated) return;
    if (initialCloudRepository) {
      didResolveWorkspaceModeRef.current = true;
      return;
    }
    const preferredMode = lastUsedWorkspaceMode || DEFAULT_WORKSPACE_MODE;
    if (preferredMode === "cloud" && !cloudSignalsSettled) return;
    didResolveWorkspaceModeRef.current = true;
    if (!localWorkspaces) return;
    setWorkspaceModeState(
      resolveWorkspaceModePreference({
        preferredMode,
        cloudModeEnabled,
        hasGithubIntegration,
        lastUsedLocalWorkspaceMode,
      }),
    );
  }, [
    settingsHydrated,
    lastUsedWorkspaceMode,
    initialCloudRepository,
    localWorkspaces,
    cloudSignalsSettled,
    cloudModeEnabled,
    hasGithubIntegration,
    lastUsedLocalWorkspaceMode,
  ]);

  const setWorkspaceMode = (mode: WorkspaceMode) => {
    didResolveWorkspaceModeRef.current = true;
    if (mode === "cloud") setRuntime("acp");
    setWorkspaceModeState(mode);
    setLastUsedWorkspaceMode(mode);
    if (mode !== "cloud") {
      setLastUsedLocalWorkspaceMode(mode);
    }
  };
  const {
    repositories: visibleCloudRepositories,
    isPending: cloudRepositoriesLoading,
    hasMore: cloudRepositoriesHasMore,
    loadMore: loadMoreCloudRepositories,
  } = useUserGithubRepositories(cloudRepoSearchQuery, isCloudRepoPickerOpen);
  const [selectedRepository, setSelectedRepository] = useState<string | null>(
    () =>
      initialCloudRepository?.toLowerCase() ??
      lastUsedCloudRepository?.toLowerCase() ??
      null,
  );
  const selectedCloudRepository = useMemo(() => {
    if (!selectedRepository) return null;
    const lower = selectedRepository.toLowerCase();
    return repositories.includes(lower) ? lower : null;
  }, [selectedRepository, repositories]);
  const { currentBranch, branchLoading, defaultBranch, busyState } =
    useGitQueries(selectedDirectory);

  const selectedGithubUserIntegrationId = selectedCloudRepository
    ? getUserIntegrationIdForRepo(selectedCloudRepository)
    : undefined;
  const selectedInstallationId = selectedCloudRepository
    ? getInstallationIdForRepo(selectedCloudRepository)
    : undefined;

  const { githubIntegrations: orgGithubIntegrations } =
    useIntegrationSelectors();
  const orgGithubIntegrationId = orgGithubIntegrations[0]?.id;

  const {
    data: cloudBranchData,
    isPending: cloudBranchesLoading,
    isRefreshing: cloudBranchesRefreshing,
    isFetchingMore: cloudBranchesFetchingMore,
    hasMore: cloudBranchesHasMore,
    loadMore: loadMoreCloudBranches,
    refresh: refreshCloudBranches,
  } = useUserGithubBranches(
    selectedInstallationId,
    selectedCloudRepository,
    cloudBranchSearchQuery,
  );
  const cloudBranches = cloudBranchData?.branches;
  const liveCloudDefaultBranch = cloudBranchData?.defaultBranch ?? null;
  // Serve the persisted default branch until the live list resolves, so the
  // majority "start on trunk" case pre-selects trunk with zero wait on a cold
  // start. The cached value is best-effort: if it's stale (a default branch
  // renamed since it was cached), `cloudDefaultBranch` switches to the live
  // value on arrival and BranchSelector re-selects it — as long as the user
  // hasn't picked a branch of their own in the meantime.
  const cloudDefaultBranch =
    liveCloudDefaultBranch ??
    (selectedCloudRepository
      ? (cachedCloudDefaultBranchMap[selectedCloudRepository] ?? null)
      : null);

  // Persist the freshly loaded default branch so the next cold start can
  // pre-select trunk immediately.
  useEffect(() => {
    if (selectedCloudRepository && liveCloudDefaultBranch) {
      setCachedCloudDefaultBranch(
        selectedCloudRepository,
        liveCloudDefaultBranch,
      );
    }
  }, [
    selectedCloudRepository,
    liveCloudDefaultBranch,
    setCachedCloudDefaultBranch,
  ]);

  const {
    branchOpen,
    branchName: newBranchName,
    branchError,
    actions: gitActions,
  } = useGitInteractionStore();

  const handleNewBranchNameChange = useCallback(
    (value: string) => {
      const { sanitized, error } = getBranchNameInputState(value);
      gitActions.setBranchName(sanitized);
      gitActions.setBranchError(error);
    },
    [gitActions],
  );

  const handleCreateBranch = useCallback(async () => {
    setIsCreatingBranch(true);

    try {
      const result = await createBranch({
        writeClient: gitWriteClient,
        repoPath: selectedDirectory || undefined,
        rawBranchName: newBranchName,
      });
      if (!result.success) {
        gitActions.setBranchError(result.error);
        return;
      }

      setSelectedBranch(result.branchName);
      gitActions.closeBranch();
    } finally {
      setIsCreatingBranch(false);
    }
  }, [selectedDirectory, newBranchName, gitActions, gitWriteClient]);

  const handleRepositorySelect = useCallback(
    (repo: string | null) => {
      if (!repo) {
        setSelectedRepository(null);
        setLastUsedCloudRepository(null);
        return;
      }

      const normalizedRepo = repo.toLowerCase();
      setSelectedRepository(normalizedRepo);
      setLastUsedCloudRepository(normalizedRepo);
    },
    [setLastUsedCloudRepository],
  );

  useEffect(() => {
    if (!initialCloudRepository) return;
    setWorkspaceModeState("cloud");
    setSelectedRepository(initialCloudRepository.toLowerCase());
  }, [initialCloudRepository]);

  const handleRefreshRepositories = useCallback(() => {
    void refreshRepositories().catch((error) => {
      toast.error("Failed to refresh repositories", {
        description:
          error instanceof Error ? error.message : "Please try again.",
      });
    });
  }, [refreshRepositories]);

  const handleRefreshBranches = useCallback(() => {
    void refreshCloudBranches().catch((error) => {
      toast.error("Failed to refresh branches", {
        description:
          error instanceof Error ? error.message : "Please try again.",
      });
    });
  }, [refreshCloudBranches]);

  const handleCloudRepoPickerOpenChange = useCallback((open: boolean) => {
    setIsCloudRepoPickerOpen(open);
    if (!open) {
      setCloudRepoSearchQuery("");
    }
  }, []);

  const handleCloudRepoSearchChange = useCallback((value: string) => {
    setCloudRepoSearchQuery(value);
  }, []);

  const handleLoadMoreCloudRepositories = useCallback(() => {
    loadMoreCloudRepositories();
  }, [loadMoreCloudRepositories]);

  const handleCloudBranchPickerClose = useCallback(() => {
    setCloudBranchSearchQuery("");
  }, []);

  const handleCloudBranchSearchChange = useCallback((value: string) => {
    setCloudBranchSearchQuery(value);
  }, []);

  const handleLoadMoreCloudBranches = useCallback(() => {
    loadMoreCloudBranches();
  }, [loadMoreCloudBranches]);

  const {
    modeOption,
    modelOption,
    thoughtOption,
    isLoading: isPreviewLoading,
    setConfigOption,
  } = usePreviewConfig(adapter);

  const lastAppliedDeepLinkConfigKey = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (isPreviewLoading) return;
    if (!initialPromptKey) return;
    if (lastAppliedDeepLinkConfigKey.current === initialPromptKey) return;
    if (!initialModel && !initialMode) return;

    if (initialModel && isValidConfigValue(modelOption, initialModel)) {
      setConfigOption(modelOption.id, initialModel);
    }
    if (initialMode && isValidConfigValue(modeOption, initialMode)) {
      setConfigOption(modeOption.id, initialMode);
    }
    lastAppliedDeepLinkConfigKey.current = initialPromptKey;
  }, [
    isPreviewLoading,
    initialPromptKey,
    initialModel,
    initialMode,
    modelOption,
    modeOption,
    setConfigOption,
  ]);

  const { folders } = useFolders();

  useEffect(() => {
    if (selectedRepository || !lastUsedCloudRepository) {
      return;
    }

    setSelectedRepository(lastUsedCloudRepository.toLowerCase());
  }, [lastUsedCloudRepository, selectedRepository]);

  useEffect(() => {
    // Clear `selectedRepository` only when the list has actually loaded AND the
    // selection is missing from it — i.e. the repo was removed from the user's
    // integrations. Bail out when `repositories` is empty: that can happen
    // transiently after `isLoadingRepos` flips false but before the
    // per-integration queries have produced data, and clearing here would
    // wipe out a freshly-supplied `initialCloudRepository` prefill.
    if (
      isLoadingRepos ||
      repositories.length === 0 ||
      !selectedRepository ||
      selectedCloudRepository
    ) {
      return;
    }

    setSelectedRepository(null);
    if (lastUsedCloudRepository === selectedRepository) {
      setLastUsedCloudRepository(null);
    }
  }, [
    isLoadingRepos,
    repositories.length,
    lastUsedCloudRepository,
    selectedCloudRepository,
    selectedRepository,
    setLastUsedCloudRepository,
  ]);

  // Switch mode for a folder-scoped prefill ("+" in the sidebar) without persisting it as
  // the user's mode preference. Marks the mode as resolved so the last-used resolver above
  // doesn't override the explicit pick.
  const switchWorkspaceModeForFolder = useCallback((mode: WorkspaceMode) => {
    didResolveWorkspaceModeRef.current = true;
    setWorkspaceModeState(mode);
  }, []);

  useInitialRepoSelectionFromFolderId({
    folderId: view.folderId,
    requestId: view.taskInputRequestId,
    folders,
    repositories,
    reposLoaded: reposReady,
    currentMode: workspaceMode,
    lastUsedLocalMode: lastUsedLocalWorkspaceMode,
    mostRecentEnvironment: view.folderRunEnvironment,
    setSelectedDirectory,
    setSelectedRepository,
    switchWorkspaceMode: switchWorkspaceModeForFolder,
  });

  useEffect(() => {
    setCloudBranchSearchQuery("");
  }, []);

  const effectiveRepoPath =
    workspaceMode === "cloud" ? selectedCloudRepository : selectedDirectory;

  const setSelectedEnvironment = useCallback(
    (envId: string | null) => {
      setSelectedEnvironmentRaw(envId);
      if (effectiveRepoPath) {
        setLastUsedEnvironment(effectiveRepoPath, envId);
      }
    },
    [effectiveRepoPath, setLastUsedEnvironment],
  );

  const [prevEffectiveRepoPath, setPrevEffectiveRepoPath] =
    useState(effectiveRepoPath);
  if (effectiveRepoPath !== prevEffectiveRepoPath) {
    setPrevEffectiveRepoPath(effectiveRepoPath);
    setSelectedBranch(null);
    setSelectedEnvironmentRaw(
      effectiveRepoPath ? getLastUsedEnvironment(effectiveRepoPath) : null,
    );
  }

  const effectiveWorkspaceMode = workspaceMode;

  // Get current values from preview config options for task creation.
  // Defaults ensure values are always passed even before the preview config loads.
  const currentModel =
    modelOption?.type === "select" ? modelOption.currentValue : undefined;
  const adapterDefault = adapter === "codex" ? "auto" : "plan";
  const modeFallback =
    defaultInitialTaskMode === "last_used" &&
    lastUsedInitialTaskMode &&
    isValidConfigValue(modeOption, lastUsedInitialTaskMode)
      ? lastUsedInitialTaskMode
      : adapterDefault;
  const currentExecutionMode =
    getCurrentModeFromConfigOptions(modeOption ? [modeOption] : undefined) ??
    modeFallback;
  const currentReasoningLevel =
    thoughtOption?.type === "select" ? thoughtOption.currentValue : undefined;

  const autoresearchEnabled = useAutoresearchEnabled();
  const armedAutoresearchDraft = useAutoresearchDraftStore(
    (state) => state.drafts[sessionId] ?? null,
  );
  // Feature-flagged (staff-gated): with the flag off the draft is inert, so
  // every armed surface (button state, header controls, submit wrapping,
  // stage-model creation params) reads as unarmed.
  const autoresearchDraft = autoresearchEnabled ? armedAutoresearchDraft : null;
  // An armed autoresearch task is created on the measure stage: its first
  // turn (the kickoff baseline) is a measurement, and the loop switches
  // stages from there.
  const effectiveModel = autoresearchDraft
    ? (autoresearchDraft.measureModel ?? currentModel)
    : currentModel;
  const effectiveReasoningLevel = autoresearchDraft
    ? (autoresearchDraft.measureEffort ?? currentReasoningLevel)
    : currentReasoningLevel;

  useWarmTask({
    workspaceMode,
    selectedRepository: selectedCloudRepository,
    githubIntegrationId: orgGithubIntegrationId,
    branch: workspaceMode === "cloud" ? selectedBranch : null,
    editorIsEmpty,
    runtimeAdapter: adapter ?? null,
    model: effectiveModel,
    reasoningEffort: effectiveReasoningLevel,
    sandboxEnvironmentId: workspaceMode === "cloud" ? selectedCloudEnvId : null,
    customImageId: workspaceMode === "cloud" ? selectedCustomImageId : null,
  });

  const branchForTaskCreation =
    effectiveWorkspaceMode === "worktree" || effectiveWorkspaceMode === "cloud"
      ? selectedBranch
      : null;

  const autoresearchService =
    useServiceOptional<AutoresearchService>(AUTORESEARCH_SERVICE);
  const autoresearchModelOptions = useMemo(
    () => toStageSelectOptions(modelOption),
    [modelOption],
  );
  const autoresearchEffortOptions = useMemo(
    () => toStageSelectOptions(thoughtOption),
    [thoughtOption],
  );

  const handleAutoresearchToggle = useCallback(() => {
    const store = useAutoresearchDraftStore.getState();
    if (store.drafts[sessionId]) {
      store.clearDraft(sessionId);
      return;
    }
    // While armed the composer's own model/effort pickers are hidden, so the
    // stage fields take over as the single source — seed them from whatever
    // the composer had selected at arm time.
    store.setDraft(sessionId, {
      direction: "maximize",
      targetValue: null,
      maxIterations: 10,
      implementModel: currentModel ?? null,
      measureModel: currentModel ?? null,
      implementEffort: currentReasoningLevel ?? null,
      measureEffort: currentReasoningLevel ?? null,
    });
    // Autoresearch needs to apply edits without stopping for each change, but
    // it should not silently inherit the broader bypass-permissions mode.
    const autonomousMode = "acceptEdits";
    if (modeOption && isValidConfigValue(modeOption, autonomousMode)) {
      setConfigOption(modeOption.id, autonomousMode);
    }
    track(ANALYTICS_EVENTS.AUTORESEARCH_ARMED, {
      default_mode: autonomousMode,
      workspace_mode: workspaceMode,
    });
  }, [
    sessionId,
    currentModel,
    currentReasoningLevel,
    modeOption,
    setConfigOption,
    workspaceMode,
  ]);

  // The preview config can still be loading when the user arms the mode;
  // backfill the stage fields once the composer's model/effort resolve so
  // the popover shows concrete values instead of "task model".
  useEffect(() => {
    if (!autoresearchDraft) return;
    const patch: Partial<typeof autoresearchDraft> = {};
    if (autoresearchDraft.implementModel === null && currentModel) {
      patch.implementModel = currentModel;
    }
    if (autoresearchDraft.measureModel === null && currentModel) {
      patch.measureModel = currentModel;
    }
    if (autoresearchDraft.implementEffort === null && currentReasoningLevel) {
      patch.implementEffort = currentReasoningLevel;
    }
    if (autoresearchDraft.measureEffort === null && currentReasoningLevel) {
      patch.measureEffort = currentReasoningLevel;
    }
    if (Object.keys(patch).length > 0) {
      useAutoresearchDraftStore.getState().updateDraft(sessionId, patch);
    }
  }, [autoresearchDraft, currentModel, currentReasoningLevel, sessionId]);

  // Registers the run against the freshly created task and opens its
  // dashboard tab; the kickoff itself rides the task's initial prompt.
  const handleAutoresearchTaskCreated = useCallback(
    (task: Task) => {
      const pending = autoresearchPendingRun.consume();
      if (!pending || !autoresearchService) return;
      try {
        autoresearchService.registerRun({ ...pending, taskId: task.id });
        const layoutStore = usePanelLayoutStore.getState();
        if (!layoutStore.getLayout(task.id)) {
          layoutStore.initializeTask(task.id);
        }
        layoutStore.openAutoresearchTab(task.id);
      } catch (error) {
        toast.error("Autoresearch setup failed", {
          description: error instanceof Error ? error.message : undefined,
        });
      }
    },
    [autoresearchService],
  );

  const {
    isCreatingTask,
    canSubmit,
    handleSubmit,
    additionalDirectories,
    setAdditionalDirectories,
  } = useTaskCreation({
    editorRef,
    sessionId,
    selectedDirectory,
    selectedRepository: selectedCloudRepository,
    githubUserIntegrationId: selectedGithubUserIntegrationId,
    workspaceMode: effectiveWorkspaceMode,
    branch: branchForTaskCreation,
    editorIsEmpty,
    adapter,
    runtime,
    executionMode: currentExecutionMode,
    model: effectiveModel,
    reasoningLevel: effectiveReasoningLevel,
    onTaskCreated,
    onTaskCreatedEffect: handleAutoresearchTaskCreated,
    environmentId: selectedEnvironment,
    sandboxEnvironmentId:
      effectiveWorkspaceMode === "cloud" && selectedCloudEnvId
        ? selectedCloudEnvId
        : undefined,
    customImageId:
      effectiveWorkspaceMode === "cloud" && selectedCustomImageId
        ? selectedCustomImageId
        : undefined,
    signalReportId: activeReportAssociation?.reportId,
    channelContext: includeChannelContext ? channelContext : undefined,
    channelName,
    channelContextId,
    allowNoRepo,
  });

  // Wraps the prompt in the autoresearch kickoff: protocol preamble first,
  // the user's composer content (chips intact) as the optimization brief.
  const handleAutoresearchSubmit = useCallback(async (): Promise<boolean> => {
    const editor = editorRef.current;
    const draft = useAutoresearchDraftStore.getState().drafts[sessionId];
    if (!editor || !draft) return handleSubmit();
    if (!canSubmit) return false;

    const content = editor.getContent();
    const override: EditorContent = {
      segments: [
        { type: "text", text: `${buildKickoffPreamble(draft)}\n\n` },
        ...content.segments,
      ],
      attachments: content.attachments,
    };
    // Stages ride through as configured; identical stages mean a single-turn
    // loop, any difference makes the run split. Unresolved fields fall back
    // to the composer's values so the recorded config is concrete.
    const resolvedRun = {
      ...draft,
      implementModel: draft.implementModel ?? currentModel ?? null,
      measureModel: draft.measureModel ?? currentModel ?? null,
      implementEffort: draft.implementEffort ?? currentReasoningLevel ?? null,
      measureEffort: draft.measureEffort ?? currentReasoningLevel ?? null,
    };
    autoresearchPendingRun.set({
      ...resolvedRun,
      instructions: contentToXml(content).trim(),
    });
    const submitted = await handleSubmit(override);
    if (submitted) {
      track(ANALYTICS_EVENTS.AUTORESEARCH_RUN_STARTED, {
        direction: resolvedRun.direction,
        has_target: resolvedRun.targetValue !== null,
        max_iterations: resolvedRun.maxIterations,
        stages_split:
          resolvedRun.implementModel !== resolvedRun.measureModel ||
          resolvedRun.implementEffort !== resolvedRun.measureEffort,
        implement_model: resolvedRun.implementModel ?? undefined,
        measure_model: resolvedRun.measureModel ?? undefined,
        implement_effort: resolvedRun.implementEffort ?? undefined,
        measure_effort: resolvedRun.measureEffort ?? undefined,
        workspace_mode: effectiveWorkspaceMode,
      });
      useAutoresearchDraftStore.getState().clearDraft(sessionId);
      useDraftStore.getState().actions.setDraft(sessionId, null);
      try {
        editorRef.current?.clear();
      } catch {
        // Task creation can navigate away and tear down the editor first.
      }
    } else {
      autoresearchPendingRun.clear();
    }
    return submitted;
  }, [
    canSubmit,
    currentModel,
    currentReasoningLevel,
    effectiveWorkspaceMode,
    handleSubmit,
    sessionId,
  ]);

  const submitTask = autoresearchDraft
    ? handleAutoresearchSubmit
    : handleSubmit;

  const handleModeChange = useCallback(
    (value: string) => {
      if (modeOption) {
        setConfigOption(modeOption.id, value);
      }
    },
    [modeOption, setConfigOption],
  );

  const handleModelChange = useCallback(
    (value: string) => {
      if (modelOption) {
        setConfigOption(modelOption.id, value);
        setLastUsedModel(value);
      }
    },
    [modelOption, setConfigOption, setLastUsedModel],
  );

  const handleThoughtChange = useCallback(
    (value: string) => {
      if (thoughtOption) {
        setConfigOption(thoughtOption.id, value);
        setLastUsedReasoningEffort(value);
      }
    },
    [thoughtOption, setConfigOption, setLastUsedReasoningEffort],
  );

  const { isOnline } = useConnectivity();
  const promptSessionId = sessionId;

  useEffect(() => {
    if (!skills) return;
    useDraftStore
      .getState()
      .actions.setCommands(promptSessionId, skills.map(skillToEditorCommand));
    return () => {
      useDraftStore.getState().actions.clearCommands(promptSessionId);
    };
  }, [promptSessionId, skills]);
  const hasHistory = useTaskInputHistoryStore((s) => s.entries.length > 0);
  const getPromptHistory = useCallback(
    () => useTaskInputHistoryStore.getState().entries.map((e) => e.text),
    [],
  );
  const handleHistorySelect = useCallback((text: string) => {
    editorRef.current?.setContent(text);
    editorRef.current?.focus();
  }, []);
  const hasPendingDraft = useCallback(
    () => !(editorRef.current?.isEmpty() ?? true),
    [],
  );
  const hints = [
    "@ to add files",
    "/ for skills",
    hasHistory ? "\u2191\u2193 for history" : "",
  ]
    .filter(Boolean)
    .join(", ");

  useAutoFocusOnTyping(editorRef, isCreatingTask);

  const handleDragEnter = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current++;
    if (e.dataTransfer.types.includes("Files")) {
      setIsDraggingFile(true);
    }
  }, []);

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current--;
    if (dragCounterRef.current === 0) {
      setIsDraggingFile(false);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    dragCounterRef.current = 0;
    setIsDraggingFile(false);

    // If dropped on the editor, Tiptap's handleDrop already handled it
    if ((e.target as HTMLElement).closest(".ProseMirror")) return;

    const files = e.dataTransfer.files;
    if (!files || files.length === 0) return;

    resolveAndAttachDroppedFiles(files, (a) =>
      editorRef.current?.addAttachment(a),
    )
      .then(() => editorRef.current?.focus())
      .catch(() => toast.error("Failed to attach files"));
  }, []);

  const handleContainerClick = useCallback((e: React.MouseEvent) => {
    if (!e.currentTarget.contains(e.target as Node)) return;
    if ((e.target as HTMLElement).closest(FOCUSABLE_SELECTOR)) return;
    editorRef.current?.focus();
  }, []);

  return (
    // biome-ignore lint/a11y/noStaticElementInteractions: drag-and-drop container
    // biome-ignore lint/a11y/useKeyWithClickEvents: click delegates focus to the editor; keyboard users tab into it directly
    <div
      ref={containerRef}
      onClick={handleContainerClick}
      onDragEnter={handleDragEnter}
      onDragLeave={handleDragLeave}
      onDragOver={handleDragOver}
      onDrop={handleDrop}
      className="relative h-full w-full"
    >
      <DropZoneOverlay isVisible={isDraggingFile} />
      <Flex height="100%" width="100%">
        {previewFile && selectedDirectory && (
          <Box className="h-full min-w-0 flex-1 border-gray-4 border-r">
            <NewTaskFilePreview
              repoPath={selectedDirectory}
              filePath={previewFile}
              onAddSelection={handleAddSelectionToPrompt}
            />
          </Box>
        )}
        <Box className="relative h-full min-w-0 flex-1">
          <Flex height="100%" className="relative px-4">
            <DotPatternBackground className="h-[100.333%]" />
            <div
              style={{
                // Raise the input when the suggestion cards are shown so the longer
                // list below it isn't squished against the bottom of the viewport.
                // Note: this is NOT tied to `editorIsEmpty` — the input keeps its
                // position as the user types so the box doesn't jump down when the
                // suggestions fade out (and back in when the prompt is cleared).
                top: suggestions && suggestions.length > 0 ? "38%" : "50%",
                transform: "translate(-50%, -50%)",
              }}
              className="absolute left-1/2 z-[1] flex w-[calc(100%-2rem)] max-w-[600px] flex-col gap-2"
            >
              <Flex
                gap="2"
                align="center"
                className="absolute bottom-full left-0 mb-2 min-w-0"
              >
                {piHarnessEnabled && workspaceMode !== "cloud" && (
                  <AgentRuntimeSelect
                    value={runtime}
                    onChange={setRuntime}
                    disabled={isCreatingTask}
                  />
                )}
                <WorkspaceModeSelect
                  value={workspaceMode}
                  onChange={setWorkspaceMode}
                  selectedCloudEnvironmentId={selectedCloudEnvId}
                  onCloudEnvironmentChange={setSelectedCloudEnvId}
                  selectedCustomImageId={selectedCustomImageId}
                  onCustomImageChange={setSelectedCustomImageId}
                  size="1"
                />
                {!allowNoRepo && workspaceMode === "worktree" && (
                  <EnvironmentSelector
                    repoPath={effectiveRepoPath ?? null}
                    value={selectedEnvironment}
                    onChange={setSelectedEnvironment}
                    disabled={isCreatingTask}
                    onCreateEnvironment={() =>
                      openSettings("environments", {
                        repoPath: effectiveRepoPath ?? undefined,
                      })
                    }
                  />
                )}
                {!allowNoRepo && (
                  <ButtonGroup
                    ref={buttonGroupRef}
                    data-tour="folder-picker"
                    data-tour-ready={
                      (
                        workspaceMode === "cloud"
                          ? selectedRepository
                          : selectedDirectory
                      )
                        ? "true"
                        : undefined
                    }
                  >
                    {workspaceMode === "cloud" ? (
                      <GitHubRepoPicker
                        value={selectedRepository}
                        onChange={handleRepositorySelect}
                        repositories={
                          isCloudRepoPickerOpen
                            ? visibleCloudRepositories
                            : repositories
                        }
                        isLoading={
                          isLoadingRepos ||
                          (isCloudRepoPickerOpen && cloudRepositoriesLoading)
                        }
                        isRefreshing={isRefreshingRepos}
                        onRefresh={handleRefreshRepositories}
                        open={isCloudRepoPickerOpen}
                        onOpenChange={handleCloudRepoPickerOpenChange}
                        searchQuery={cloudRepoSearchQuery}
                        onSearchQueryChange={handleCloudRepoSearchChange}
                        hasMore={cloudRepositoriesHasMore}
                        onLoadMore={handleLoadMoreCloudRepositories}
                        placeholder="Select repository..."
                        size="1"
                        disabled={isCreatingTask}
                      />
                    ) : (
                      <FolderPicker
                        value={selectedDirectory}
                        onChange={setSelectedDirectory}
                        placeholder="Select repository..."
                        anchor={buttonGroupRef}
                      />
                    )}
                    <BranchSelector
                      repoPath={
                        workspaceMode === "cloud"
                          ? selectedCloudRepository
                          : selectedDirectory
                      }
                      currentBranch={currentBranch}
                      defaultBranch={
                        workspaceMode === "cloud"
                          ? cloudDefaultBranch
                          : defaultBranch
                      }
                      disabled={
                        isCreatingTask ||
                        (workspaceMode === "cloud" && !selectedCloudRepository)
                      }
                      loading={
                        workspaceMode === "cloud" ? false : branchLoading
                      }
                      workspaceMode={workspaceMode}
                      selectedBranch={selectedBranch}
                      onBranchSelect={setSelectedBranch}
                      busyState={busyState}
                      cloudBranches={cloudBranches}
                      cloudBranchesLoading={cloudBranchesLoading}
                      isRefreshing={cloudBranchesRefreshing}
                      cloudBranchesFetchingMore={cloudBranchesFetchingMore}
                      cloudBranchesHasMore={cloudBranchesHasMore}
                      cloudSearchQuery={cloudBranchSearchQuery}
                      onCloudPickerClose={handleCloudBranchPickerClose}
                      onCloudSearchChange={handleCloudBranchSearchChange}
                      onCloudBranchCommit={handleCloudBranchPickerClose}
                      onCloudLoadMore={handleLoadMoreCloudBranches}
                      onRefresh={
                        workspaceMode === "cloud"
                          ? handleRefreshBranches
                          : undefined
                      }
                      anchor={buttonGroupRef}
                    />
                  </ButtonGroup>
                )}
                {!allowNoRepo && workspaceMode !== "cloud" && (
                  <AdditionalDirectoriesButton
                    values={additionalDirectories}
                    onChange={setAdditionalDirectories}
                    primaryDirectory={selectedDirectory}
                    disabled={isCreatingTask}
                  />
                )}
                {cloudRegion === "dev" && (
                  <Flex align="center" gap="1" className="shrink-0">
                    <span
                      className="inline-block h-2 w-2 rounded-full bg-orange-9"
                      aria-hidden
                    />
                    <Text color="orange" className="font-medium text-[13px]">
                      Dev
                    </Text>
                  </Flex>
                )}
              </Flex>

              <Flex direction="column" gap="0">
                {autoresearchDraft && (
                  <div className="mb-3 rounded-md border border-gray-6 bg-gray-2 px-3.5 py-3">
                    <AutoresearchComposerControls
                      draft={autoresearchDraft}
                      modelOptions={autoresearchModelOptions}
                      effortOptions={autoresearchEffortOptions}
                      disabled={isCreatingTask}
                      onChange={(patch) =>
                        useAutoresearchDraftStore
                          .getState()
                          .updateDraft(sessionId, patch)
                      }
                      onExit={() =>
                        useAutoresearchDraftStore
                          .getState()
                          .clearDraft(sessionId)
                      }
                    />
                  </div>
                )}
                <PromptInput
                  ref={editorRef}
                  sessionId={promptSessionId}
                  placeholder={
                    autoresearchDraft
                      ? "Example: Reduce memory usage measured by `pnpm bench:memory` without changing behavior."
                      : `What do you want to ship? ${hints}`
                  }
                  editorHeight="large"
                  disabled={isCreatingTask}
                  isLoading={isCreatingTask}
                  autoFocus
                  clearOnSubmit={false}
                  submitDisabledExternal={
                    !canSubmit ||
                    isCreatingTask ||
                    !isOnline ||
                    isPreviewLoading
                  }
                  tourTarget="task-input"
                  repoPath={selectedDirectory}
                  modeOption={modeOption}
                  onModeChange={handleModeChange}
                  allowBypassPermissions={allowBypassPermissions}
                  autoresearch={
                    autoresearchService && autoresearchEnabled
                      ? {
                          active: !!autoresearchDraft,
                          onToggle: handleAutoresearchToggle,
                        }
                      : undefined
                  }
                  enableCommands
                  enableBashMode={false}
                  modelSelector={
                    autoresearchDraft ? null : (
                      <UnifiedModelSelector
                        modelOption={modelOption}
                        adapter={adapter ?? "claude"}
                        onAdapterChange={setAdapter}
                        disabled={isCreatingTask}
                        isConnecting={isPreviewLoading}
                        onModelChange={handleModelChange}
                      />
                    )
                  }
                  historyButton={
                    <PromptHistoryDialog
                      onSelect={handleHistorySelect}
                      hasPendingDraft={hasPendingDraft}
                      disabled={isCreatingTask}
                    />
                  }
                  reasoningSelector={
                    autoresearchDraft ? null : (
                      <ReasoningLevelSelector
                        thoughtOption={thoughtOption}
                        adapter={adapter}
                        onChange={handleThoughtChange}
                        disabled={isCreatingTask}
                        isLoading={isPreviewLoading}
                      />
                    )
                  }
                  getPromptHistory={getPromptHistory}
                  onEmptyChange={handleEditorEmptyChange}
                  onSubmitClick={() => void submitTask()}
                  onSubmit={() => {
                    if (canSubmit) void submitTask();
                  }}
                />
                {activeReportAssociation && (
                  <div className="-mt-px mx-2 flex select-none items-center justify-between gap-2 rounded-b-md border border-blue-6 border-t-0 bg-blue-2 px-2 py-1 text-[12px] text-blue-11">
                    <span className="flex min-w-0 flex-1 items-center gap-1">
                      <span className="shrink-0">
                        This task will be associated with report
                      </span>
                      <button
                        type="button"
                        onClick={handleOpenAssociatedReport}
                        className="min-w-0 truncate text-left font-medium underline underline-offset-2 hover:text-blue-12"
                      >
                        {activeReportAssociation.title || "Untitled report"}
                      </button>
                    </span>
                    <Tooltip content="Exit Inbox mode">
                      <button
                        type="button"
                        onClick={handleDismissReportAssociation}
                        aria-label="Exit Inbox mode"
                        className="flex h-5 w-5 shrink-0 items-center justify-center rounded text-blue-10 hover:bg-blue-4 hover:text-blue-12"
                      >
                        <X size={12} />
                      </button>
                    </Tooltip>
                  </div>
                )}
                {includeChannelContext && (
                  <div className="-mt-px mx-2 flex select-none flex-wrap items-center gap-1.5 rounded-b-md border border-gray-6 border-t-0 bg-gray-2 px-2 py-1 text-[12px] text-gray-11">
                    <span className="shrink-0 text-gray-10">Using:</span>
                    <span className="inline-flex items-center gap-1 rounded-[var(--radius-1)] bg-[var(--gray-a3)] px-1.5 py-px font-medium text-[var(--gray-11)]">
                      {onContextChipClick ? (
                        <Tooltip content="View this CONTEXT.md">
                          <button
                            type="button"
                            onClick={onContextChipClick}
                            className="inline-flex min-w-0 items-center gap-1 rounded text-[var(--gray-11)] hover:text-gray-12"
                          >
                            <FileText size={12} />
                            <span className="truncate">
                              {channelName ? `#${channelName} ` : ""}CONTEXT.md
                            </span>
                          </button>
                        </Tooltip>
                      ) : (
                        <>
                          <FileText size={12} />
                          <span className="truncate">
                            {channelName ? `#${channelName} ` : ""}CONTEXT.md
                          </span>
                        </>
                      )}
                      <Tooltip content="Don't include this CONTEXT.md">
                        <button
                          type="button"
                          onClick={() => setChannelContextDismissed(true)}
                          aria-label="Remove CONTEXT.md from prompt"
                          className="ml-0.5 inline-flex size-3.5 items-center justify-center rounded text-gray-10 hover:bg-gray-5 hover:text-gray-12"
                        >
                          <X size={12} />
                        </button>
                      </Tooltip>
                    </span>
                  </div>
                )}
                {effectiveWorkspaceMode === "cloud" &&
                  !isLoadingRepos &&
                  !hasGithubIntegration && (
                    <div className="mx-2 mt-2">
                      <CloudGithubMissingNotice />
                    </div>
                  )}
              </Flex>
              <div className="absolute top-full right-0 left-0 z-10">
                {suggestions ? (
                  <AnimatePresence>
                    {suggestions.length > 0 && editorIsEmpty && (
                      <motion.div
                        key="suggestions"
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.2, ease: "easeInOut" }}
                        className="mt-6 flex flex-col gap-2"
                      >
                        <Text
                          size="1"
                          weight="medium"
                          className="px-2.5 text-(--gray-11)"
                        >
                          Suggestions
                        </Text>
                        <div className="grid grid-cols-2 gap-2">
                          {suggestions.map((suggestion) => (
                            <SuggestedPromptCard
                              key={suggestion.label}
                              suggestion={suggestion}
                              onSelect={() => {
                                onSuggestionSelect?.(suggestion.label);
                                // Use pending content (not setContent) so the
                                // multi-line template — intro + "User input:" fill-in
                                // lines — keeps its line breaks; focuses at the end.
                                useDraftStore
                                  .getState()
                                  .actions.setPendingContent(sessionId, {
                                    segments: [
                                      { type: "text", text: suggestion.prompt },
                                    ],
                                  });
                                // Bug/feature suggestions start in plan mode; the
                                // analysis ones start in auto mode. Suggestions
                                // without a mode leave the composer's mode as-is.
                                if (
                                  suggestion.mode &&
                                  isValidConfigValue(
                                    modeOption,
                                    suggestion.mode,
                                  )
                                ) {
                                  setConfigOption(
                                    modeOption.id,
                                    suggestion.mode,
                                  );
                                }
                              }}
                            />
                          ))}
                        </div>
                      </motion.div>
                    )}
                  </AnimatePresence>
                ) : (
                  <NewTaskSuggestions
                    repoPath={selectedDirectory || null}
                    workspaceMode={effectiveWorkspaceMode}
                    disabled={isCreatingTask}
                  />
                )}
              </div>
            </div>
          </Flex>
        </Box>
      </Flex>

      <GitBranchDialog
        open={branchOpen}
        onOpenChange={(open) => {
          if (!open) gitActions.closeBranch();
        }}
        branchName={newBranchName}
        onBranchNameChange={handleNewBranchNameChange}
        onConfirm={handleCreateBranch}
        isSubmitting={isCreatingBranch}
        error={branchError}
      />
    </div>
  );
}
