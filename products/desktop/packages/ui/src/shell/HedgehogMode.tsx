import { useService } from "@posthog/di/react";
import { useEffect, useRef, useState } from "react";
import { useMeQuery } from "../features/auth/useMeQuery";
import { useSettingsStore } from "../features/settings/settingsStore";
import { captureException } from "./analytics";
import {
  HEDGEHOG_MODE_HOST,
  type HedgehogModeHandle,
  type HedgehogModeHost,
} from "./hedgehogModeHost";
import { logger } from "./logger";
import { useRendererWindowFocusStore } from "./rendererWindowFocusStore";

const log = logger.scope("hedgehog-mode");
const MAX_CONTEXT_LOSS_REMOUNTS = 3;
const REMOUNT_DELAY_MS = 2000;
const CONTEXT_CHECK_INTERVAL_MS = 10_000;

export function HedgehogMode() {
  const hedgehogMode = useSettingsStore((s) => s.hedgehogMode);
  const setHedgehogMode = useSettingsStore((s) => s.setHedgehogMode);
  const { data: user } = useMeQuery();
  const host = useService<HedgehogModeHost>(HEDGEHOG_MODE_HOST);
  const containerRef = useRef<HTMLDivElement>(null);
  const handleRef = useRef<HedgehogModeHandle | null>(null);
  const [gameDead, setGameDead] = useState(false);
  // Counts context losses across effect re-runs. An effect-local counter
  // resets whenever a dependency changes (user config settling at boot, a
  // settings write), which re-arms three more remount attempts per re-run
  // and lets a crashing GPU cycle the game indefinitely. Reset only when
  // the user turns the mode off.
  const contextLossesRef = useRef(0);

  useEffect(() => {
    if (hedgehogMode) return;
    setGameDead(false);
    contextLossesRef.current = 0;
  }, [hedgehogMode]);

  useEffect(() => {
    if (!hedgehogMode || gameDead || !containerRef.current || !host) return;

    let cancelled = false;
    let remountTimer: ReturnType<typeof setTimeout> | null = null;
    const container = containerRef.current;

    const hedgehogConfig = user?.hedgehog_config as Record<
      string,
      unknown
    > | null;
    const actorOptions = hedgehogConfig?.actor_options;

    const destroyGame = () => {
      try {
        handleRef.current?.destroy();
      } catch (err) {
        log.error("Failed to destroy hedgehog mode game", err);
      }
      handleRef.current = null;
      container.replaceChildren();
    };

    // A game whose rendering context died composites its full-window canvas
    // as an opaque sheet over the whole app, so it must leave the DOM
    // immediately.
    const handleContextLost = () => {
      if (!handleRef.current) return;
      contextLossesRef.current += 1;
      const losses = contextLossesRef.current;
      log.error("Hedgehog mode WebGL context lost", { losses });
      captureException(new Error("Hedgehog mode WebGL context lost"), {
        source: "hedgehog-mode",
        losses,
      });
      destroyGame();
      if (losses > MAX_CONTEXT_LOSS_REMOUNTS) {
        setGameDead(true);
        return;
      }
      remountTimer = setTimeout(() => {
        log.warn("Remounting hedgehog mode after WebGL context loss", {
          attempt: losses,
        });
        mountGame();
      }, REMOUNT_DELAY_MS);
    };

    // Backup for a missed context-loss callback (e.g. swallowed across
    // sleep/wake), so a dead canvas can never linger on screen undetected.
    const checkContext = () => {
      if (document.hidden) return;
      if (handleRef.current?.isContextLost()) handleContextLost();
    };

    const mountGame = () => {
      if (cancelled || handleRef.current) return;
      host
        .mount(container, {
          actorOptions,
          onQuit: () => setHedgehogMode(false),
          onContextLost: handleContextLost,
        })
        .then((handle) => {
          if (cancelled) {
            handle.destroy();
            return;
          }
          handleRef.current = handle;
        })
        .catch((err) => {
          log.error("Failed to mount hedgehog mode", err);
        });
    };

    mountGame();
    const contextCheckInterval = setInterval(
      checkContext,
      CONTEXT_CHECK_INTERVAL_MS,
    );
    const unsubscribeFocusCheck = useRendererWindowFocusStore.subscribe(
      (state) => {
        if (state.focused) checkContext();
      },
    );

    return () => {
      cancelled = true;
      clearInterval(contextCheckInterval);
      unsubscribeFocusCheck();
      if (remountTimer) {
        clearTimeout(remountTimer);
      }
      destroyGame();
    };
  }, [hedgehogMode, gameDead, user?.hedgehog_config, setHedgehogMode, host]);

  return (
    <div
      ref={containerRef}
      style={{
        zIndex: 999998,
        visibility: hedgehogMode && !gameDead ? "visible" : "hidden",
      }}
      className="pointer-events-none absolute inset-0"
    />
  );
}
