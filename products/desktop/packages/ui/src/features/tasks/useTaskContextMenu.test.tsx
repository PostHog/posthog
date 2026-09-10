import { act, renderHook } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const hoisted = vi.hoisted(() => ({
  showTaskContextMenu: vi.fn(),
  useChannels: vi.fn(),
  useFeatureFlag: vi.fn(),
}));

vi.mock("@posthog/host-router/react", () => ({
  useHostTRPCClient: () => ({
    contextMenu: {
      showTaskContextMenu: { mutate: hoisted.showTaskContextMenu },
    },
  }),
}));

vi.mock("@posthog/ui/features/archive/useArchiveTask", () => ({
  useArchiveTask: () => ({ archiveTask: vi.fn() }),
}));

vi.mock("@posthog/ui/features/canvas/hooks/useChannels", () => ({
  useChannels: hoisted.useChannels,
}));

vi.mock("@posthog/ui/features/canvas/hooks/useFileTaskToChannel", () => ({
  useFileTaskToChannel: () => vi.fn(),
}));

vi.mock("@posthog/ui/features/external-apps/useExternalAppAction", () => ({
  useExternalAppAction: () => vi.fn(),
}));

vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: hoisted.useFeatureFlag,
}));

vi.mock("@posthog/ui/features/suspension/useRestoreTask", () => ({
  useRestoreTask: () => ({ restoreTask: vi.fn() }),
}));

vi.mock("@posthog/ui/features/suspension/useSuspendTask", () => ({
  useSuspendTask: () => ({ suspendTask: vi.fn() }),
}));

vi.mock("@posthog/ui/features/tasks/useTaskCrudMutations", () => ({
  useDeleteTask: () => ({ deleteWithConfirm: vi.fn() }),
}));

import { useTaskContextMenu } from "./useTaskContextMenu";

const SUPPORT_CHANNEL = {
  id: "c1",
  name: "support",
  channelType: "public" as const,
  starred: false,
};

describe("useTaskContextMenu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    hoisted.showTaskContextMenu.mockResolvedValue({ action: null });
    hoisted.useChannels.mockReturnValue({
      channels: [SUPPORT_CHANNEL],
      isLoading: false,
    });
  });

  async function openMenu() {
    const { result } = renderHook(() => useTaskContextMenu());
    await act(() =>
      result.current.showContextMenu({ id: "t1", title: "Task" }, {
        preventDefault: vi.fn(),
        stopPropagation: vi.fn(),
      } as unknown as React.MouseEvent),
    );
  }

  // `enabled: false` stops the fetch but still hands back whatever an ungated
  // surface already put in the shared cache, so the flag has to gate the list.
  it.each([
    { expectedChannels: [SUPPORT_CHANNEL], flag: "on", flagEnabled: true },
    { expectedChannels: [], flag: "off", flagEnabled: false },
  ])(
    "sends the native menu the project's spaces with the bluebird flag $flag",
    async ({ expectedChannels, flagEnabled }) => {
      hoisted.useFeatureFlag.mockReturnValue(flagEnabled);

      await openMenu();

      expect(hoisted.showTaskContextMenu).toHaveBeenCalledWith(
        expect.objectContaining({ channels: expectedChannels }),
      );
      expect(hoisted.useChannels).toHaveBeenCalledWith({
        enabled: flagEnabled,
      });
    },
  );
});
