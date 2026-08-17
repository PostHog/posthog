import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import type { Meta, StoryObj } from "@storybook/react-vite";
import { useEffect } from "react";
import type { ZoomLevel } from "../camera";
import { cellStatusInput, wantsAttention } from "../cellStatus";
import type { ZoomCell, ZoomColumn, ZoomGrid } from "../useZoomGrid";
import { useZoomCanvasStore } from "../zoomCanvasStore";
import { ZoomCanvasView } from "./ZoomCanvasView";

/**
 * Fixture columns. Invented, not taken from anyone's task list — these are read
 * by whoever opens the story, so they say only what a public repo can say.
 */
const FIXTURE: { name: string; tasks: Partial<TaskData>[] }[] = [
  {
    name: "acme/storefront",
    tasks: [
      { title: "Cart totals drift on currency switch", needsPermission: true },
      { title: "Add express checkout to the mini cart", isGenerating: true },
      { title: "Trim the product grid bundle", taskRunStatus: "completed" },
      { title: "Retire the legacy promo banner", isUnread: true },
      { title: "Backfill product slugs" },
    ],
  },
  {
    name: "acme/billing",
    tasks: [
      { title: "Proration is off by a day on downgrades", isGenerating: true },
      { title: "Invoice PDFs miss the tax line", taskRunStatus: "failed" },
      { title: "Retry dunning webhooks", taskRunStatus: "completed" },
    ],
  },
  {
    name: "acme/platform",
    tasks: [
      { title: "Split the deploy pipeline per service", needsPermission: true },
      { title: "Cache warm-up runs before health checks pass" },
      { title: "Drop the unused metrics sidecar", taskRunStatus: "completed" },
      { title: "Move secrets to the new vault path", isSuspended: true },
      { title: "Rotate the staging database credentials" },
      { title: "Prune stale feature-flag rollouts", isUnread: true },
    ],
  },
  {
    name: "acme/docs",
    tasks: [
      { title: "Rewrite the quickstart for the new CLI", isGenerating: true },
      { title: "Fix broken anchors in the API reference" },
    ],
  },
];

function buildTask(overrides: Partial<TaskData>, id: string): TaskData {
  return {
    id,
    title: "Untitled",
    createdAt: 0,
    // MockDate pins the clock in Storybook, so a fixed offset keeps the
    // relative timestamps stable across snapshots.
    lastActivityAt: 1_700_000_000_000,
    isGenerating: false,
    isUnread: false,
    isPinned: false,
    needsPermission: false,
    repository: null,
    isSuspended: false,
    folderPath: null,
    cloudPrUrl: null,
    branchName: null,
    linkedBranch: null,
    ...overrides,
  };
}

function buildGrid(): ZoomGrid {
  const columns: ZoomColumn[] = [];
  const cells: ZoomCell[] = [];

  FIXTURE.forEach((group, column) => {
    const columnCells = group.tasks.map((overrides, row) => ({
      task: buildTask(overrides, `${column}-${row}`),
      status: cellStatusInput(buildTask(overrides, `${column}-${row}`)),
      position: { column, row },
      columnName: group.name,
    }));
    columns.push({ id: group.name, name: group.name, cells: columnCells });
    cells.push(...columnCells);
  });

  return {
    columns,
    cells,
    needsAttention: cells.filter((cell) => wantsAttention(cell.task)),
    size: {
      columns: columns.length,
      rows: Math.max(...columns.map((column) => column.cells.length)),
    },
    isLoading: false,
  };
}

const GRID = buildGrid();

function Harness({ zoom }: { zoom: ZoomLevel }) {
  useEffect(() => {
    useZoomCanvasStore.setState({
      zoom,
      column: 1,
      desiredRow: 1,
      anchorTaskId: null,
    });
  }, [zoom]);

  return (
    <div className="h-[720px] w-[1180px]">
      <ZoomCanvasView grid={GRID} />
    </div>
  );
}

const meta: Meta<typeof Harness> = {
  title: "ZoomCanvas/ZoomCanvasView",
  component: Harness,
  parameters: { layout: "centered" },
};
export default meta;
type Story = StoryObj<typeof Harness>;

/** One task fills the window — what Escape pulls you out of. */
export const Session: Story = { args: { zoom: "session" } };

/** The selection with its neighbours clipped at the edges. */
export const Arena: Story = { args: { zoom: "arena" } };

/** Every project and task at once. The canvas is its own map here. */
export const World: Story = { args: { zoom: "world" } };
