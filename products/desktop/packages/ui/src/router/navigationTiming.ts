type Navigation = {
  id: number;
  startedAt: number;
};

export function createNavigationTiming(): {
  start: () => void;
  settle: (record: (durationMs: number) => void) => void;
} {
  let nextId = 0;
  let navigation: Navigation | null = null;

  return {
    start: () => {
      navigation = { id: ++nextId, startedAt: performance.now() };
    },
    settle: (record) => {
      const settledNavigation = navigation;
      if (!settledNavigation) return;

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (navigation?.id !== settledNavigation.id) return;

          navigation = null;
          record(performance.now() - settledNavigation.startedAt);
        });
      });
    },
  };
}
