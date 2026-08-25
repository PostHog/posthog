import { useEffect, useState } from "react";

// `delay <= 0` syncs synchronously and is the documented way to collapse the
// window (e.g. flip to 0 when a popover closes so reopen starts clean).
export function useDebounce<T>(value: T, delay: number): T {
  const [debouncedValue, setDebouncedValue] = useState(value);

  useEffect(() => {
    if (delay <= 0) {
      setDebouncedValue(value);
      return;
    }
    const handle = setTimeout(() => setDebouncedValue(value), delay);
    return () => clearTimeout(handle);
  }, [value, delay]);

  return debouncedValue;
}
