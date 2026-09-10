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
  let unsubscribeFromVisibilityChange: (() => void) | null = null;

  const clearNavigation = (): void => {
    navigation = null;
    unsubscribeFromVisibilityChange?.();
    unsubscribeFromVisibilityChange = null;
  };

  return {
    start: () => {
      clearNavigation();
      if (document.visibilityState !== "visible") return;

      const nextNavigation = { id: ++nextId, startedAt: performance.now() };
      navigation = nextNavigation;
      const onVisibilityChange = (): void => {
        if (
          document.visibilityState !== "visible" &&
          navigation?.id === nextNavigation.id
        ) {
          clearNavigation();
        }
      };
      document.addEventListener("visibilitychange", onVisibilityChange);
      unsubscribeFromVisibilityChange = () => {
        document.removeEventListener("visibilitychange", onVisibilityChange);
      };
    },
    settle: (record) => {
      const settledNavigation = navigation;
      if (!settledNavigation) return;

      requestAnimationFrame(() => {
        requestAnimationFrame(() => {
          if (navigation?.id !== settledNavigation.id) return;
          if (document.visibilityState !== "visible") {
            clearNavigation();
            return;
          }

          clearNavigation();
          record(performance.now() - settledNavigation.startedAt);
        });
      });
    },
  };
}
