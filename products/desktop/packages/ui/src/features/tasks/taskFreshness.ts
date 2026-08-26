import type { Task } from "@posthog/shared/domain-types";

function parseTime(value: string | null | undefined): number {
  const timestamp = value ? Date.parse(value) : Number.NEGATIVE_INFINITY;
  return Number.isFinite(timestamp) ? timestamp : Number.NEGATIVE_INFINITY;
}

export function getTaskFreshness(task: Task): number {
  return Math.max(
    parseTime(task.updated_at),
    parseTime(task.latest_run?.updated_at),
  );
}

export function pickFreshestTask(a: Task, b: Task | null | undefined): Task;
export function pickFreshestTask(
  a: Task | null | undefined,
  b: Task | null | undefined,
): Task | undefined;
export function pickFreshestTask(
  a: Task | null | undefined,
  b: Task | null | undefined,
): Task | undefined {
  if (!a) return b ?? undefined;
  if (!b) return a;
  return getTaskFreshness(b) > getTaskFreshness(a) ? b : a;
}
