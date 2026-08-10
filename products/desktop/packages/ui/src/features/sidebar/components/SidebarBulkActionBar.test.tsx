import type { SidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SidebarBulkActionBar } from "./SidebarBulkActionBar";

if (typeof globalThis.ResizeObserver === "undefined") {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}

function makeActions(
  overrides: Partial<SidebarBulkActions> = {},
): SidebarBulkActions {
  return {
    selectedCount: 3,
    runningCount: 0,
    stopsCloudSandbox: false,
    pinDirection: "pin",
    pinLabel: "Pin 3 sessions",
    channels: [
      { id: "c1", name: "support", channelType: "public", starred: false },
    ],
    archiveSelected: vi.fn(),
    pinSelected: vi.fn(),
    addSelectedToCommandCenter: vi.fn(),
    fileSelectedTo: vi.fn(),
    archiveDisabledReason: null,
    pinDisabledReason: null,
    commandCenterDisabledReason: null,
    fileDisabledReason: null,
    isArchiving: false,
    isPinning: false,
    isFiling: false,
    ...overrides,
  };
}

function renderBar(overrides: Partial<SidebarBulkActions> = {}) {
  return render(
    <SidebarBulkActionBar
      actions={makeActions(overrides)}
      onClearSelection={vi.fn()}
      onArchive={vi.fn()}
    />,
  );
}

describe("SidebarBulkActionBar", () => {
  it("renders nothing with an empty selection", () => {
    const { container } = renderBar({ selectedCount: 0 });

    expect(container).toBeEmptyDOMElement();
  });

  it("shows the selected count and the actions", () => {
    renderBar();

    expect(screen.getByText("3 selected")).toBeInTheDocument();
    expect(screen.getByLabelText("Pin 3 sessions")).toBeInTheDocument();
    expect(screen.getByLabelText("Archive 3 sessions")).toBeInTheDocument();
    expect(
      screen.getByLabelText("Add 3 sessions to Command Center"),
    ).toBeInTheDocument();
  });

  it("shows the unpin label when the selection is all pinned", () => {
    renderBar({ pinDirection: "unpin", pinLabel: "Unpin 3 sessions" });

    expect(screen.getByLabelText("Unpin 3 sessions")).toBeInTheDocument();
    expect(screen.queryByLabelText("Pin 3 sessions")).not.toBeInTheDocument();
  });

  it("hides File to when the action is unavailable", () => {
    renderBar({ channels: [], fileDisabledReason: "there are no channels" });

    expect(
      screen.queryByLabelText("File 3 sessions to a channel"),
    ).not.toBeInTheDocument();
  });

  it("singularizes the labels for one session", () => {
    renderBar({ selectedCount: 1, pinLabel: "Pin 1 session" });

    expect(screen.getByText("1 selected")).toBeInTheDocument();
    expect(screen.getByLabelText("Archive 1 session")).toBeInTheDocument();
  });
});
