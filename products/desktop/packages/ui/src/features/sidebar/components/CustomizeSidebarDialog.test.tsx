import { LOOPS_FLAG } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { Theme } from "@radix-ui/themes";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

type CapturedDragEvent = {
  operation: { source?: { id?: string }; target?: { id?: string } };
  canceled?: boolean;
};

const { track, dndCapture, featureFlags } = vi.hoisted(() => ({
  track: vi.fn(),
  featureFlags: new Map<string, boolean>(),
  dndCapture: {} as {
    onDragStart?: (event: CapturedDragEvent) => void;
    onDragOver?: (event: CapturedDragEvent) => void;
    onDragEnd?: (event: CapturedDragEvent) => void;
  },
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));
vi.mock("@posthog/ui/features/feature-flags/useFeatureFlag", () => ({
  useFeatureFlag: (key: string) => featureFlags.get(key) ?? true,
}));
vi.mock("@dnd-kit/react", () => ({
  DragDropProvider: ({
    onDragStart,
    onDragOver,
    onDragEnd,
    children,
  }: {
    onDragStart?: (event: CapturedDragEvent) => void;
    onDragOver?: (event: CapturedDragEvent) => void;
    onDragEnd?: (event: CapturedDragEvent) => void;
    children?: React.ReactNode;
  }) => {
    dndCapture.onDragStart = onDragStart;
    dndCapture.onDragOver = onDragOver;
    dndCapture.onDragEnd = onDragEnd;
    return <>{children}</>;
  },
}));
vi.mock("@dnd-kit/react/sortable", () => ({
  useSortable: () => ({
    ref: () => {},
    handleRef: () => {},
    isDragging: false,
  }),
}));

import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { CustomizeSidebarSettings } from "./CustomizeSidebarDialog";

function renderSettings() {
  return render(
    <Theme>
      <CustomizeSidebarSettings />
    </Theme>,
  );
}

function dragStart(sourceId: string) {
  act(() => {
    dndCapture.onDragStart?.({ operation: { source: { id: sourceId } } });
  });
}

function dragOver(sourceId: string, targetId: string) {
  act(() => {
    dndCapture.onDragOver?.({
      operation: { source: { id: sourceId }, target: { id: targetId } },
    });
  });
}

function dragEnd(
  sourceId: string,
  { cancel = false }: { cancel?: boolean } = {},
) {
  act(() => {
    dndCapture.onDragEnd?.({
      operation: { source: { id: sourceId } },
      canceled: cancel,
    });
  });
}

function rowLabels() {
  return screen
    .getAllByRole("checkbox")
    .map((checkbox) => checkbox.closest("label")?.textContent);
}

describe("CustomizeSidebarSettings", () => {
  beforeEach(() => {
    track.mockReset();
    featureFlags.clear();
    useSidebarStore.setState({ navItemOverrides: {}, navItemOrder: [] });
  });

  it("omits items whose features are unavailable", () => {
    featureFlags.set(LOOPS_FLAG, false);

    renderSettings();

    expect(
      screen.queryByRole("checkbox", { name: "Loops" }),
    ).not.toBeInTheDocument();
  });

  it("unchecking a visible item demotes it and tracks the change", async () => {
    const user = userEvent.setup();
    renderSettings();

    await user.click(screen.getByRole("checkbox", { name: "Command Center" }));

    expect(useSidebarStore.getState().navItemOverrides["command-center"]).toBe(
      false,
    );
    expect(track).toHaveBeenCalledWith(ANALYTICS_EVENTS.SIDEBAR_CUSTOMIZED, {
      item: "command_center",
      visible: false,
    });
  });

  it("checking a hidden item promotes it and tracks the change", async () => {
    const user = userEvent.setup();
    useSidebarStore.setState({ navItemOverrides: { inbox: false } });
    renderSettings();

    await user.click(screen.getByRole("checkbox", { name: "Inbox" }));

    expect(useSidebarStore.getState().navItemOverrides.inbox).toBe(true);
    expect(track).toHaveBeenCalledWith(ANALYTICS_EVENTS.SIDEBAR_CUSTOMIZED, {
      item: "inbox",
      visible: true,
    });
  });

  it("renders rows in the stored order", () => {
    useSidebarStore.setState({ navItemOrder: ["configure", "inbox"] });
    renderSettings();

    expect(rowLabels().slice(0, 2)).toEqual(["Configure", "Inbox"]);
  });

  it("previews on dragover and persists only on drop", () => {
    renderSettings();

    dragStart("loops");
    dragOver("loops", "inbox");

    expect(rowLabels()[0]).toBe("Loops");
    expect(useSidebarStore.getState().navItemOrder).toEqual([]);
    expect(track).not.toHaveBeenCalled();

    dragEnd("loops");

    expect(useSidebarStore.getState().navItemOrder).toEqual([
      "loops",
      "inbox",
      "command-center",
      "contexts",
      "activity",
      "configure",
    ]);
    expect(track).toHaveBeenCalledWith(ANALYTICS_EVENTS.SIDEBAR_REORDERED, {
      item: "loops",
      to_index: 0,
    });
  });

  it("ignores a repeated dragover for the same source and target", () => {
    renderSettings();

    dragStart("loops");
    dragOver("loops", "inbox");
    dragOver("loops", "inbox");

    expect(rowLabels()[0]).toBe("Loops");

    dragEnd("loops");

    expect(useSidebarStore.getState().navItemOrder[0]).toBe("loops");
  });

  it("a canceled drag drops the preview and leaves the store untouched", () => {
    renderSettings();

    dragStart("loops");
    dragOver("loops", "inbox");
    dragEnd("loops", { cancel: true });

    expect(rowLabels()[0]).toBe("Inbox");
    expect(useSidebarStore.getState().navItemOrder).toEqual([]);
    expect(track).not.toHaveBeenCalled();
  });

  it("a drop without movement neither persists nor tracks", () => {
    renderSettings();

    dragStart("loops");
    dragEnd("loops");

    expect(useSidebarStore.getState().navItemOrder).toEqual([]);
    expect(track).not.toHaveBeenCalled();
  });

  it("reset clears the stored order back to the default", async () => {
    const user = userEvent.setup();
    useSidebarStore.setState({ navItemOrder: ["loops", "inbox"] });
    renderSettings();

    await user.click(screen.getByRole("button", { name: "Reset" }));

    expect(useSidebarStore.getState().navItemOrder).toEqual([]);
    expect(rowLabels()[0]).toBe("Inbox");
  });
});
