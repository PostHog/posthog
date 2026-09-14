export function createNavigationTiming(): {
  start: () => void;
  settle: (
    record: (
      durationMs: number,
      visibilityAtSettle: DocumentVisibilityState,
    ) => void,
  ) => void;
} {
  let startedAt: number | null = null;

  return {
    start: () => {
      startedAt = performance.now();
    },
    settle: (record) => {
      if (startedAt === null) return;

      const durationMs = performance.now() - startedAt;
      startedAt = null;
      record(durationMs, document.visibilityState);
    },
  };
}
