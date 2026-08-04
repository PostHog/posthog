export type DiffWorkerFactory = () => Worker;

export const DIFF_WORKER_FACTORY = Symbol.for("posthog.ui.DiffWorkerFactory");
