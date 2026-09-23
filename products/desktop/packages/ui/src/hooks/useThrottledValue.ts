import { useEffect, useRef, useState } from "react";

/**
 * Emit `value` at most once every `intervalMs` while `enabled`. While disabled the live
 * value passes straight through, and it keeps passing through after re-enabling until the
 * next emission lands, so the returned value never moves backwards.
 */
export function useThrottledValue<T>(
  value: T,
  intervalMs: number,
  enabled = true,
): T {
  const [throttled, setThrottled] = useState(value);
  const lastEmittedAtRef = useRef(0);
  const staleRef = useRef(false);

  useEffect(() => {
    if (!enabled) {
      staleRef.current = true;
      return;
    }
    const emit = (): void => {
      lastEmittedAtRef.current = Date.now();
      staleRef.current = false;
      setThrottled(value);
    };
    const elapsed = Date.now() - lastEmittedAtRef.current;
    if (elapsed >= intervalMs) {
      emit();
      return;
    }
    const timer = setTimeout(emit, intervalMs - elapsed);
    return () => clearTimeout(timer);
  }, [value, intervalMs, enabled]);

  return enabled && !staleRef.current ? throttled : value;
}
