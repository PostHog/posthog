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
      {
        id: "c1",
        name: "support",
        channelType: "public",
        starred: false,
        repositories: [],
        createdBy: null,
      },
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
  it("shows no bar with an empty selection", () => {
    renderBar({ selectedCount: 0 });

    expect(screen.queryByLabelText(/^Archive/)).not.toBeInTheDocument();
    expect(screen.queryByText(/selected$/)).not.toBeInTheDocument();
  });

  // The count is the only announcement of a selection, and a live region has to
  // predate its own text to be read out, so it outlives the bar it describes.
  it("keeps a live region across the selection appearing", () => {
    const { container, rerender } = renderBar({ selectedCount: 0 });
    const region = container.querySelector("[aria-live=polite]");
    expect(region).toHaveTextContent("");

    rerender(
      <SidebarBulkActionBar
        actions={makeActions({ selectedCount: 2 })}
        onClearSelection={vi.fn()}
        onArchive={vi.fn()}
      />,
    );

    expect(container.querySelector("[aria-live=polite]")).toBe(region);
    expect(region).toHaveTextContent("2 sessions selected");
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
