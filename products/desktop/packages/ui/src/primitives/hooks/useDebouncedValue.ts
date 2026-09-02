import { useEffect, useState } from "react";

/** Debounces `value` by `delayMs`. While waiting, `isPending` is true. */
export function useDebouncedValue<T>(
  value: T,
  delayMs: number,
): {
  debounced: T;
  isPending: boolean;
} {
  const [debounced, setDebounced] = useState(value);
  const isPending = value !== debounced;

  useEffect(() => {
    if (value === debounced) return;
    const id = setTimeout(() => setDebounced(value), delayMs);
    return () => clearTimeout(id);
  }, [value, delayMs, debounced]);

  return { debounced, isPending };
}
