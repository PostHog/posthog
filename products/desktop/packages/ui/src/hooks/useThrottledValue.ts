import { useEffect, useRef, useState } from "react";

export function useThrottledValue<T>(
  value: T,
  intervalMs: number,
  enabled = true,
): T {
  const [throttled, setThrottled] = useState(value);
  const lastEmittedAtRef = useRef(0);
  const wasEnabledRef = useRef(enabled);

  useEffect(() => {
    wasEnabledRef.current = enabled;
    if (!enabled) return;
    const elapsed = Date.now() - lastEmittedAtRef.current;
    if (elapsed >= intervalMs) {
      lastEmittedAtRef.current = Date.now();
      setThrottled(value);
      return;
    }
    const timer = setTimeout(() => {
      lastEmittedAtRef.current = Date.now();
      setThrottled(value);
    }, intervalMs - elapsed);
    return () => clearTimeout(timer);
  }, [value, intervalMs, enabled]);

  const justEnabled = enabled && !wasEnabledRef.current;
  return enabled && !justEnabled ? throttled : value;
}
