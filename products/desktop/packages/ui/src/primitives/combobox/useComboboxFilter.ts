import { defaultFilter } from "cmdk";
import Fuse, { type IFuseOptions } from "fuse.js";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useDebounce } from "../hooks/useDebounce";

const DEFAULT_LIMIT = 50;
const MIN_FUZZY_SCORE = 0.1;
const DEBOUNCE_MS = 150;
// fuse.js scores run 0 (perfect) → 1 (worst); only keep reasonably close matches.
const FUSE_THRESHOLD = 0.4;

/** Weighted fields for the opt-in fuse.js search path. */
export type ComboboxSearchKeys<T> = NonNullable<IFuseOptions<T>["keys"]>;

interface UseComboboxFilterOptions<T> {
  /** Maximum number of items to render. Defaults to 50. */
  limit?: number;
  /** Values pinned to the top regardless of score. */
  pinned?: string[];
  /** Popover open state. Search resets when this becomes false. */
  open?: boolean;
  /**
   * Opt-in weighted fuzzy search across multiple fields, via fuse.js. Each key
   * carries a weight (e.g. name above description), and items whose `getValue`
   * starts with the query are promoted for exact-match priority. When omitted,
   * scoring falls back to cmdk single-string matching over `getValue`.
   *
   * Pass a stable reference (a module constant) — a fresh array every render
   * rebuilds the fuse index each time.
   */
  keys?: ComboboxSearchKeys<T>;
}

interface UseComboboxFilterResult<T> {
  filtered: T[];
  onSearchChange: (value: string) => void;
  hasMore: boolean;
  moreCount: number;
}

/**
 * Fuzzy-filters and caps a list of items for use with Combobox.
 *
 * Prefer passing `items` directly to `Combobox.Content` which handles all
 * wiring automatically. Use this hook directly only when you need custom
 * control over the filtering lifecycle.
 */
export function useComboboxFilter<T>(
  items: T[],
  options?: UseComboboxFilterOptions<T>,
  getValue?: (item: T) => string,
): UseComboboxFilterResult<T> {
  const limit = options?.limit ?? DEFAULT_LIMIT;
  const pinned = options?.pinned;
  const open = options?.open;
  const keys = options?.keys;
  const [inputValue, setInputValue] = useState("");
  // delay=0 while closed so the next open starts on fresh empty-query results,
  // not a flash of the previous filtered set.
  const search = useDebounce(inputValue, open ? DEBOUNCE_MS : 0);

  useEffect(() => {
    if (!open) setInputValue("");
  }, [open]);

  const resolve = useCallback(
    (item: T): string => (getValue ? getValue(item) : String(item)),
    [getValue],
  );

  // Build the fuse index only on the opt-in weighted path. `keys` must be a
  // stable reference or this rebuilds every render.
  const fuse = useMemo(
    () =>
      keys
        ? new Fuse(items, {
            keys,
            threshold: FUSE_THRESHOLD,
            ignoreLocation: true,
            includeScore: true,
          })
        : null,
    [items, keys],
  );

  const { filtered, totalMatches } = useMemo(() => {
    const query = search.trim();

    // Scores below are normalised so higher always means a better match,
    // letting the sort logic below stay identical across both paths.
    let scored: Array<{ item: T; score: number }>;
    if (query && fuse) {
      // Weighted multi-key fuzzy search. fuse scores 0 (best) → 1 (worst), so
      // invert to higher-is-better, and promote prefix matches (+1) so an
      // exact-ish hit on the leading field always outranks a fuzzy one.
      const lowerQuery = query.toLowerCase();
      scored = fuse.search(query).map(({ item, score }) => {
        const prefix = resolve(item).toLowerCase().startsWith(lowerQuery);
        return { item, score: (prefix ? 1 : 0) + (1 - (score ?? 1)) };
      });
    } else if (query) {
      // cmdk's fuzzy matcher can produce very low scores for scattered
      // single-character matches (e.g. "vojta" matching v-o-j-t-a across
      // "chore-remoVe-cOhort-Join-aTtempt"), so we require a minimum score to
      // avoid noisy results.
      scored = [];
      for (const item of items) {
        const score = defaultFilter(resolve(item), query);
        if (score >= MIN_FUZZY_SCORE) scored.push({ item, score });
      }
    } else {
      scored = items.map((item) => ({ item, score: 0 }));
    }

    const total = scored.length;

    // Sort: pinned first (in order), then by score descending (stable for equal scores)
    if (pinned) {
      const pinnedSet = new Set(pinned);
      scored.sort((a, b) => {
        const aVal = resolve(a.item);
        const bVal = resolve(b.item);
        const aPinned = pinnedSet.has(aVal);
        const bPinned = pinnedSet.has(bVal);
        if (aPinned && !bPinned) return -1;
        if (!aPinned && bPinned) return 1;
        if (aPinned && bPinned) {
          return pinned.indexOf(aVal) - pinned.indexOf(bVal);
        }
        return b.score - a.score;
      });
    } else if (query) {
      scored.sort((a, b) => b.score - a.score);
    }

    return {
      filtered: scored.slice(0, limit).map((s) => s.item),
      totalMatches: total,
    };
  }, [items, search, limit, pinned, resolve, fuse]);

  return {
    filtered,
    onSearchChange: setInputValue,
    hasMore: totalMatches > filtered.length,
    moreCount: Math.max(0, totalMatches - filtered.length),
  };
}
