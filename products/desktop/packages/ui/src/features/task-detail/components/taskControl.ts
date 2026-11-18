import type { Task } from "@posthog/shared/domain-types";

// Mirrors the server's legacy unchanneled task-control origins.
const TEAM_VISIBLE_ORIGIN_PRODUCTS = new Set([
  "signal_report",
  "signals_scout",
  "onboarding",
  "hogdesk",
  "workflow",
]);

export function canControlTask(
  task: Task,
  isTaskAuthor: boolean | undefined,
): boolean {
  return (
    isTaskAuthor !== false ||
    (!task.channel && TEAM_VISIBLE_ORIGIN_PRODUCTS.has(task.origin_product))
  );
}
