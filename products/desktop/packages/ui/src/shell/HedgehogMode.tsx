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

  useEffect(() => {
    if (hedgehogMode) return;
    setGameDead(false);
  }, [hedgehogMode]);

  useEffect(() => {
    if (!hedgehogMode || gameDead || !containerRef.current || !host) return;

    let cancelled = false;
    let losses = 0;
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
      losses += 1;
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
      className="pointer-events-none fixed inset-0"
    />
  );
}
