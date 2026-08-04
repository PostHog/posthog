import { useEffect, useState } from "react";

const envIdleMs = Number(
  (import.meta as { env?: Record<string, string | undefined> }).env
    ?.VITE_PRESENCE_IDLE_MS,
);

/**
 * How long without any window input before the user counts as away.
 *
 * Tuned against the workspace-server agent idle timeout (15 min): once the
 * activity heartbeat stops, the server reclaims the idle agent process
 * (~300-400MB RSS per session) after its own timeout, so an away user frees
 * memory after presence-idle + server-idle. Reconnect on return is automatic
 * and takes seconds.
 *
 * VITE_PRESENCE_IDLE_MS overrides it (dev/test only — e.g. the memory bench
 * shrinks it to verify the suspend/reclaim/reconnect loop in minutes).
 */
export const USER_PRESENCE_IDLE_MS =
  Number.isFinite(envIdleMs) && envIdleMs > 0 ? envIdleMs : 10 * 60 * 1000;

/** Presence bookkeeping is coarse; avoid work on every mousemove. */
const ACTIVITY_THROTTLE_MS = 15 * 1000;

const PRESENCE_EVENTS = [
  "pointerdown",
  "pointermove",
  "keydown",
  "wheel",
  "focus",
] as const;

/**
 * True while the user is actively using the app window; flips to false after
 * `idleMs` without any input, and back to true on the next interaction.
 *
 * Input only counts while the window has focus — a stray mouse-over of an
 * unfocused window is not use. The window gaining focus counts by itself.
 */
export function useUserPresence(
  idleMs: number = USER_PRESENCE_IDLE_MS,
): boolean {
  const [present, setPresent] = useState(true);

  useEffect(() => {
    let lastActivityAt = Date.now();
    let lastRecordedAt = lastActivityAt;
    // Scale the throttle down for small idleMs (test knobs): a fixed 15s
    // throttle with idleMs <= 15s would drop every input and pin the user
    // "away" while they actively interact.
    const throttleMs = Math.min(ACTIVITY_THROTTLE_MS, idleMs / 4);

    const onActivity = (event: Event) => {
      if (event.type !== "focus" && !document.hasFocus()) return;
      const now = Date.now();
      if (now - lastRecordedAt < throttleMs) return;
      lastRecordedAt = now;
      lastActivityAt = now;
      setPresent(true);
    };

    for (const event of PRESENCE_EVENTS) {
      window.addEventListener(event, onActivity, { passive: true });
    }
    const checkIntervalMs = Math.min(60 * 1000, Math.max(idleMs / 2, 1000));
    const idleCheck = setInterval(() => {
      if (Date.now() - lastActivityAt >= idleMs) {
        setPresent(false);
      }
    }, checkIntervalMs);

    return () => {
      for (const event of PRESENCE_EVENTS) {
        window.removeEventListener(event, onActivity);
      }
      clearInterval(idleCheck);
    };
  }, [idleMs]);

  return present;
}
