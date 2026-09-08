import type { EditorContent } from "@posthog/core/message-editor/content";
import {
  contentToPlainText,
  contentToXml,
  textToContent,
} from "@posthog/core/message-editor/content";
import type { Task } from "@posthog/shared/domain-types";
import { useTaskInputPrefillStore } from "@posthog/ui/features/task-detail/stores/taskInputPrefillStore";
import {
  pendingTaskPromptStoreApi,
  usePendingTaskPromptStore,
} from "@posthog/ui/shell/pendingTaskPromptStore";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const createTaskMock = vi.hoisted(() => vi.fn());
const invalidateTasksMock = vi.hoisted(() => vi.fn());
const openTaskMock = vi.hoisted(() => vi.fn());
const trackMock = vi.hoisted(() => vi.fn());
const cloudSubscription = vi.hoisted(() => ({
  cloudSubscriptionOn: false,
  cloudFlagEnabled: true,
}));

vi.mock("@posthog/di/react", () => ({
  useService: () => ({ createTask: createTaskMock }),
  useServiceOptional: () => undefined,
}));
vi.mock("@posthog/host-router/react", () => ({
  useHostTRPC: () => ({
    workspace: { getAll: { queryKey: () => ["workspaces"] } },
    additionalDirectories: {
      listDefaults: {
        queryOptions: () => ({
          queryKey: ["additional-directories"],
          queryFn: async () => [],
        }),
      },
    },
  }),
  useHostTRPCClient: () => ({
    workspace: { getWorktreeFileUsage: { query: vi.fn() } },
  }),
}));
vi.mock("@posthog/ui/features/canvas/hooks/useTaskChannels", () => ({
  useTaskChannels: () => ({ personalChannel: null }),
}));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: () => false,
}));
vi.mock("@posthog/ui/features/settings/adapterSubscription", () => ({
  useAdapterSubscription: () => ({
    ...cloudSubscription,
    flagEnabled: false,
    loginState: "logged-out",
    subscriptionOn: false,
  }),
  subscriptionModelAccess: () =>
    cloudSubscription.cloudSubscriptionOn ? "own-subscription" : undefined,
}));
vi.mock("@posthog/ui/features/tasks/useTaskCrudMutations", () => ({
  useCreateTask: () => ({ invalidateTasks: invalidateTasksMock }),
}));
vi.mock("@posthog/ui/features/tasks/useTasks", () => ({
  useTasks: () => ({ data: [] }),
}));
vi.mock("@posthog/ui/features/local-mcp/useLocalMcpCloudServers", () => ({
  useLocalMcpCloudServers: () => ({ servers: [], isLoading: false }),
}));
vi.mock("../../../hooks/useConnectivity", () => ({
  useConnectivity: () => ({ isOnline: true }),
}));
vi.mock("../../billing/preflightCloudUsage", () => ({
  assertCloudUsageAvailable: async () => true,
}));
vi.mock("../../../primitives/toast", () => ({
  toast: { error: vi.fn() },
}));
vi.mock("../../../shell/analytics", () => ({ track: trackMock }));
vi.mock("../../../shell/logger", () => ({
  logger: {
    scope: () => ({ warn: vi.fn(), error: vi.fn(), info: vi.fn() }),
  },
}));
vi.mock("@posthog/ui/features/notifications/errorDetails", () => ({
  toastError: vi.fn(),
}));
vi.mock("@posthog/ui/features/auth/store", () => ({
  useAuthStateValue: () => true,
}));
vi.mock("@posthog/ui/router/useOpenTask", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@posthog/ui/router/useOpenTask")>();
  return { ...actual, openTask: openTaskMock };
});

import type { EditorHandle } from "../../message-editor/types";
import { useTaskCreation } from "./useTaskCreation";

const KICKOFF_PREAMBLE =
  "AUTORESEARCH KICKOFF — protocol instructions generated for the run";

function fakeTask(): Task {
  return {
    id: "task-1",
    task_number: 1,
    slug: "task-1",
    title: "Optimize the login flow",
    description: "Optimize the login flow",
    created_at: "2026-06-15T00:00:00.000Z",
    updated_at: "2026-06-15T00:00:00.000Z",
    origin_product: "user_created",
  };
}

function editorHandle(content: EditorContent): { current: EditorHandle } {
  return {
    current: {
      focus: vi.fn(),
      blur: vi.fn(),
      clear: vi.fn(),
      isEmpty: () => false,
      getContent: () => content,
      getText: () => contentToPlainText(content),
      setContent: vi.fn(),
      insertEditorContent: vi.fn(),
      insertChip: vi.fn(),
      removeChipById: vi.fn(),
      replaceChipAttrs: vi.fn(),
      addAttachment: vi.fn(),
      removeAttachment: vi.fn(),
    },
  };
}

function wrapper({ children }: { children: ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

function renderTaskCreation(
  content: EditorContent,
  workspaceMode: "local" | "cloud" = "local",
  runtime: "acp" | "pi" = "acp",
) {
  return renderHook(
    () =>
      useTaskCreation({
        editorRef: editorHandle(content),
        sessionId: "session-1",
        selectedDirectory: "/repo",
        allowNoRepo: true,
        workspaceMode,
        runtime,
        adapter: "claude",
        editorIsEmpty: false,
      }),
    { wrapper },
  );
}

describe("useTaskCreation prompt records", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createTaskMock.mockReset();
    cloudSubscription.cloudSubscriptionOn = false;
    usePendingTaskPromptStore.setState({ byKey: {}, _hasHydrated: true });
    useTaskInputPrefillStore.setState({ prefill: {} });
  });

  it("omits subscription billing when Pi is selected", async () => {
    cloudSubscription.cloudSubscriptionOn = true;
    createTaskMock.mockResolvedValueOnce({
      success: true,
      data: { task: fakeTask(), workspace: null },
    });
    const { result } = renderTaskCreation(
      textToContent("Check the build"),
      "cloud",
      "pi",
    );

    await act(async () => {
      expect(await result.current.handleSubmit()).toBe(true);
    });

    expect(createTaskMock).toHaveBeenCalledOnce();
    expect(createTaskMock.mock.calls[0][0]).toMatchObject({
      runtime: "pi",
      claudeCloudModelAccess: undefined,
      claudeModelAccess: undefined,
      codexModelAccess: undefined,
    });
  });

  it.each(["local", "cloud"] as const)(
    "keeps the submitted prompt visible after successful %s creation until the chat takes over",
    async (workspaceMode) => {
      const brief = textToContent("Check the build");
      createTaskMock.mockImplementationOnce(async (_input, onTaskReady) => {
        const output = { task: fakeTask(), workspace: null };
        onTaskReady?.(output);
        return { success: true, data: output };
      });

      const { result } = renderTaskCreation(brief, workspaceMode);
      await act(async () => {
        expect(await result.current.handleSubmit()).toBe(true);
      });

      expect(pendingTaskPromptStoreApi.get("task-1")?.contentXml).toBe(
        contentToXml(brief).trim(),
      );
      expect(pendingTaskPromptStoreApi.getRecoverableNewestFirst()).toEqual([]);
    },
  );

  it("keeps the typed brief, not the kickoff preamble, in the recovery record after a late autoresearch failure", async () => {
    const brief = textToContent("Optimize the login flow");
    // Mirrors handleAutoresearchSubmit: the request content wraps the brief.
    const override: EditorContent = {
      segments: [
        { type: "text", text: `${KICKOFF_PREAMBLE}\n\n` },
        ...brief.segments,
      ],
      attachments: brief.attachments,
    };

    createTaskMock.mockImplementationOnce(async (_input, onTaskReady) => {
      // The late failure: onTaskReady already ran, so the record moved to the
      // task id and the origin tab sits on the rolled-back task.
      onTaskReady?.({ task: fakeTask(), workspace: null });
      return { success: false, error: "boom", failedStep: "create" };
    });

    const { result } = renderTaskCreation(brief);
    await act(async () => {
      await result.current.handleSubmit(override, brief);
    });

    const record = pendingTaskPromptStoreApi.get("task-1");
    expect(record?.promptText).toBe("Optimize the login flow");
    expect(record?.contentXml).toBe(contentToXml(brief).trim());
    expect(record?.contentXml).not.toContain("AUTORESEARCH");

    // Recovery stages the brief back into the composer, so a resubmit through
    // the still-armed autoresearch wrapper prepends the preamble only once.
    const { prefill } = useTaskInputPrefillStore.getState();
    expect(prefill.recoveredFromKey).toBe("task-1");
    expect(prefill.initialContent).toEqual(
      expect.objectContaining({ segments: brief.segments }),
    );
  });

  it("derives the record from the composer content on a plain submit", async () => {
    const brief = textToContent("Fix the flaky test");

    createTaskMock.mockImplementationOnce(async (_input, onTaskReady) => {
      onTaskReady?.({ task: fakeTask(), workspace: null });
      return { success: false, error: "boom", failedStep: "create" };
    });

    const { result } = renderTaskCreation(brief);
    await act(async () => {
      await result.current.handleSubmit();
    });

    expect(pendingTaskPromptStoreApi.get("task-1")?.contentXml).toBe(
      contentToXml(brief).trim(),
    );
  });
});
