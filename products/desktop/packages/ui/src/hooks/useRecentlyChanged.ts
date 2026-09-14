import { useEffect, useState } from "react";

/**
 * True from the first render that sees a new `value` until the value holds still for
 * `settleMs`. The change is detected during render, not in an effect, so a caller can
 * switch how it renders in the same commit the new value arrives in.
 */
export function useRecentlyChanged<T>(value: T, settleMs: number): boolean {
  const [seen, setSeen] = useState<{ value: T; changing: boolean }>({
    value,
    changing: false,
  });

  if (!Object.is(seen.value, value)) {
    setSeen({ value, changing: true });
  }

  useEffect(() => {
    if (!seen.changing) return;
    const timer = setTimeout(
      () => setSeen((current) => ({ ...current, changing: false })),
      settleMs,
    );
    return () => clearTimeout(timer);
  }, [seen, settleMs]);

  return seen.changing;
}
