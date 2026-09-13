import { useEffect, useRef, useState } from "react";

export function useRecentlyChanged<T>(value: T, settleMs: number): boolean {
  const [changing, setChanging] = useState(false);
  const mountedValueRef = useRef<{ value: T } | null>({ value });

  useEffect(() => {
    if (mountedValueRef.current) {
      const unchanged = Object.is(mountedValueRef.current.value, value);
      mountedValueRef.current = null;
      if (unchanged) return;
    }
    setChanging(true);
    const timer = setTimeout(() => setChanging(false), settleMs);
    return () => clearTimeout(timer);
  }, [value, settleMs]);

  return changing;
}
