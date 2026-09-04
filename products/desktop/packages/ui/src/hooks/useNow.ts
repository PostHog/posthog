import { useSyncExternalStore } from "react";

/**
 * How often subscribers see the clock move. Presence tiers are minutes wide,
 * so a minute is fine grain, and the tick is shared by every subscriber.
 */
const TICK_MS = 60_000;

const listeners = new Set<() => void>();
let now = Date.now();
let timer: ReturnType<typeof setInterval> | undefined;

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  // One interval for the whole app, started by the first subscriber and
  // stopped by the last: dozens of rows reading the clock should not mean
  // dozens of timers.
  if (!timer) {
    timer = setInterval(() => {
      now = Date.now();
      for (const notify of listeners) notify();
    }, TICK_MS);
  }
  return () => {
    listeners.delete(listener);
    if (listeners.size === 0 && timer) {
      clearInterval(timer);
      timer = undefined;
    }
  };
}

function snapshot(): number {
  return now;
}

/**
 * The wall clock, in epoch milliseconds, re-rendering the caller once a minute.
 *
 * For anything derived from "how long ago": a value memoized on data alone
 * never notices the clock moving, so a face that should stop pulsing after
 * three minutes keeps pulsing until the data happens to change.
 */
export function useNow(): number {
  return useSyncExternalStore(subscribe, snapshot, snapshot);
}
