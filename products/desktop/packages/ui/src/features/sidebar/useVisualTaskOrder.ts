import type {
  SidebarData,
  TaskData,
} from "@posthog/core/sidebar/sidebarData.types";
import { useMemo } from "react";
import { useSidebarStore } from "./sidebarStore";

export function useVisualTaskOrder(sidebarData: SidebarData): TaskData[] {
  const organizeMode = useSidebarStore((state) => state.organizeMode);
  const collapsedSections = useSidebarStore((state) => state.collapsedSections);

  return useMemo(() => {
    const result: TaskData[] = [];

    result.push(...sidebarData.pinnedTasks);

    if (organizeMode === "by-project") {
      for (const group of sidebarData.groupedTasks) {
        const isExpanded = !collapsedSections.has(group.id);
        if (isExpanded) {
          result.push(...group.tasks);
        }
      }
    } else {
      result.push(...sidebarData.flatTasks);
    }

    return result;
  }, [
    sidebarData.pinnedTasks,
    sidebarData.groupedTasks,
    sidebarData.flatTasks,
    organizeMode,
    collapsedSections,
  ]);
}
