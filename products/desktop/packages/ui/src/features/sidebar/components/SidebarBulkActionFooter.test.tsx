import type { SidebarBulkActions } from "@posthog/ui/features/sidebar/useSidebarBulkActions";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SidebarBulkActionFooter } from "./SidebarBulkActionFooter";

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
    channels: [],
    archiveSelected: vi.fn().mockResolvedValue(undefined),
    pinSelected: vi.fn(),
    addSelectedToCommandCenter: vi.fn(),
    fileSelectedTo: vi.fn(),
    archiveDisabledReason: null,
    pinDisabledReason: null,
    commandCenterDisabledReason: null,
    fileDisabledReason: "this project has no channels to file to",
    isArchiving: false,
    isPinning: false,
    isFiling: false,
    ...overrides,
  };
}

describe("SidebarBulkActionFooter", () => {
  it("confirms before archiving rather than archiving on the click", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const actions = makeActions();
    render(
      <SidebarBulkActionFooter actions={actions} onClearSelection={vi.fn()} />,
    );

    await user.click(screen.getByLabelText("Archive 3 sessions"));

    expect(actions.archiveSelected).not.toHaveBeenCalled();
    expect(await screen.findByText("Archive 3 sessions?")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Archive" }));
    expect(actions.archiveSelected).toHaveBeenCalledOnce();
  });

  // Archiving clears the selection, so a dialog reading the count live would
  // retitle itself "Archive 0 sessions?" while it is still open.
  it("keeps the count it opened with after the selection empties", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const { rerender } = render(
      <SidebarBulkActionFooter
        actions={makeActions()}
        onClearSelection={vi.fn()}
      />,
    );

    await user.click(screen.getByLabelText("Archive 3 sessions"));
    expect(await screen.findByText("Archive 3 sessions?")).toBeInTheDocument();

    rerender(
      <SidebarBulkActionFooter
        actions={makeActions({ selectedCount: 0, isArchiving: true })}
        onClearSelection={vi.fn()}
      />,
    );

    expect(screen.getByText("Archive 3 sessions?")).toBeInTheDocument();
  });

  it("holds the dialog open when Escape lands mid-archive", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    const { rerender } = render(
      <SidebarBulkActionFooter
        actions={makeActions()}
        onClearSelection={vi.fn()}
      />,
    );
    await user.click(screen.getByLabelText("Archive 3 sessions"));
    expect(await screen.findByText("Archive 3 sessions?")).toBeInTheDocument();

    rerender(
      <SidebarBulkActionFooter
        actions={makeActions({ isArchiving: true })}
        onClearSelection={vi.fn()}
      />,
    );
    await user.keyboard("{Escape}");

    expect(screen.getByText("Archive 3 sessions?")).toBeInTheDocument();
  });
});
