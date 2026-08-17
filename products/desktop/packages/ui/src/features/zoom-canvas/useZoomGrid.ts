import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import { useMemo } from "react";
import { useAppView } from "../../router/useAppView";
import type { TaskStatusInput } from "../sidebar/components/items/taskStatusVocabulary";
import { useSidebarData } from "../sidebar/useSidebarData";
import type { GridPosition, GridSize } from "./camera";
import { cellStatusInput, wantsAttention } from "./cellStatus";

export interface ZoomCell {
  task: TaskData;
  status: TaskStatusInput;
  position: GridPosition;
  /** The column's name, carried so a cell can label itself without a lookup. */
  columnName: string;
}

export interface ZoomColumn {
  id: string;
  name: string;
  cells: ZoomCell[];
}

export interface ZoomGrid {
  columns: ZoomColumn[];
  size: GridSize;
  /** Every cell flattened, in column-then-row order. */
  cells: ZoomCell[];
  /** Cells waiting on a person, in the same order — what ⌥N walks. */
  needsAttention: ZoomCell[];
  isLoading: boolean;
}

/**
 * The canvas layout, from the same task data the sidebar reads: one column per
 * project, one row per task inside it.
 *
 * Projects with no tasks are dropped rather than drawn as empty columns — an
 * empty column is a hole the camera can land in with nothing to show.
 */
export function useZoomGrid(): ZoomGrid {
  const view = useAppView();
  const { groupedTasks, isLoading } = useSidebarData({ activeView: view });

  return useMemo(() => {
    const columns: ZoomColumn[] = [];
    const cells: ZoomCell[] = [];

    for (const group of groupedTasks) {
      if (group.tasks.length === 0) continue;
      const column = columns.length;
      const columnCells = group.tasks.map((task, row) => ({
        task,
        status: cellStatusInput(task),
        position: { column, row },
        columnName: group.name,
      }));
      columns.push({ id: group.id, name: group.name, cells: columnCells });
      cells.push(...columnCells);
    }

    return {
      columns,
      cells,
      needsAttention: cells.filter((cell) => wantsAttention(cell.task)),
      size: {
        columns: columns.length,
        rows: Math.max(0, ...columns.map((column) => column.cells.length)),
      },
      isLoading,
    };
  }, [groupedTasks, isLoading]);
}
