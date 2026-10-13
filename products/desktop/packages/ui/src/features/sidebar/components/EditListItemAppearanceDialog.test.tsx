import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

type CapturedDragEvent = {
  operation: { source?: { id?: string }; target?: { id?: string } };
  canceled?: boolean;
};

const { track, dndCapture } = vi.hoisted(() => ({
  track: vi.fn(),
  dndCapture: {} as {
    onDragStart?: (event: CapturedDragEvent) => void;
    onDragOver?: (event: CapturedDragEvent) => void;
    onDragEnd?: (event: CapturedDragEvent) => void;
  },
}));

vi.mock("@posthog/ui/shell/analytics", () => ({ track }));
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
import { EditListItemAppearanceDialog } from "./EditListItemAppearanceDialog";

function renderDialog(onOpenChange = vi.fn()) {
  render(
    <EditListItemAppearanceDialog
      surface="sidebar"
      open
      onOpenChange={onOpenChange}
    />,
  );
  return { onOpenChange };
}

describe("EditListItemAppearanceDialog", () => {
  beforeEach(() => {
    track.mockReset();
    useSidebarStore.setState({ listItemMetadataFields: ["repository"] });
  });

  it("previews selected metadata and saves added fields", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();

    expect(screen.getByText("posthog/code")).toBeInTheDocument();

    await user.click(screen.getByRole("checkbox", { name: "Branch" }));
    expect(screen.getByText("posthog/session-list")).toBeInTheDocument();

    await user.click(screen.getByText("Save"));

    expect(useSidebarStore.getState().listItemMetadataFields).toEqual([
      "repository",
      "branch",
    ]);
    expect(track).toHaveBeenCalledWith(
      ANALYTICS_EVENTS.TASK_LIST_APPEARANCE_CHANGED,
      {
        secondary_fields: ["repository", "branch"],
        secondary_field_count: 2,
        surface: "sidebar",
      },
    );
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("does not persist draft changes when canceled", async () => {
    const user = userEvent.setup();
    const { onOpenChange } = renderDialog();

    await user.click(screen.getByRole("checkbox", { name: "Creator" }));
    await user.click(screen.getByText("Cancel"));

    expect(useSidebarStore.getState().listItemMetadataFields).toEqual([
      "repository",
    ]);
    expect(track).not.toHaveBeenCalled();
    expect(onOpenChange.mock.calls[0]?.[0]).toBe(false);
  });

  it("saves selected fields in their dragged order", async () => {
    const user = userEvent.setup();
    useSidebarStore.setState({
      listItemMetadataFields: ["repository", "branch"],
    });
    renderDialog();

    act(() => {
      dndCapture.onDragStart?.({
        operation: { source: { id: "branch" } },
      });
      dndCapture.onDragOver?.({
        operation: {
          source: { id: "branch" },
          target: { id: "repository" },
        },
      });
    });

    await user.click(screen.getByText("Save"));

    expect(useSidebarStore.getState().listItemMetadataFields).toEqual([
      "branch",
      "repository",
    ]);
  });

  it("restores the pre-drag order when a drag is canceled", async () => {
    const user = userEvent.setup();
    useSidebarStore.setState({
      listItemMetadataFields: ["repository", "branch"],
    });
    renderDialog();

    act(() => {
      dndCapture.onDragStart?.({
        operation: { source: { id: "branch" } },
      });
      dndCapture.onDragOver?.({
        operation: {
          source: { id: "branch" },
          target: { id: "repository" },
        },
      });
      dndCapture.onDragEnd?.({
        operation: { source: { id: "branch" } },
        canceled: true,
      });
    });

    await user.click(screen.getByText("Save"));

    expect(useSidebarStore.getState().listItemMetadataFields).toEqual([
      "repository",
      "branch",
    ]);
  });
});
