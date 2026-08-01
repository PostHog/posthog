import { useSettingsStore } from "@posthog/ui/features/settings/settingsStore";
import { useThemeStore } from "@posthog/ui/shell/themeStore";
import { Box } from "@radix-ui/themes";
import "@xterm/xterm/css/xterm.css";

import { resolveTerminalFontFamily } from "@posthog/core/terminal/resolveTerminalFontFamily";
import { useService } from "@posthog/di/react";
import {
  SHELL_CLIENT,
  type ShellClient,
} from "@posthog/ui/features/terminal/shellClient";
import { terminalManager } from "@posthog/ui/features/terminal/TerminalManager";
import { useCallback, useEffect, useRef } from "react";

export interface TerminalProps {
  sessionId: string;
  persistenceKey: string;
  cwd?: string;
  initialState?: string;
  taskId?: string;
  command?: string;
  onReady?: () => void;
  onExit?: (exitCode?: number) => void;
}

export function Terminal({
  sessionId,
  persistenceKey,
  cwd,
  initialState,
  taskId,
  command,
  onReady,
  onExit,
}: TerminalProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const shellClient = useService<ShellClient>(SHELL_CLIENT);
  const isDarkMode = useThemeStore((state) => state.isDarkMode);
  const terminalFont = useSettingsStore((s) => s.terminalFont);
  const terminalCustomFontFamily = useSettingsStore(
    (s) => s.terminalCustomFontFamily,
  );
  const terminalGpuRendering = useSettingsStore((s) => s.terminalGpuRendering);

  // Create instance (idempotent)
  useEffect(() => {
    if (!terminalManager.has(sessionId)) {
      terminalManager.create({
        sessionId,
        persistenceKey,
        cwd,
        initialState,
        taskId,
        command,
      });
    }
  }, [sessionId, persistenceKey, cwd, initialState, taskId, command]);

  // Attach/detach from DOM
  useEffect(() => {
    if (!terminalRef.current) return;

    terminalManager.attach(sessionId, terminalRef.current);
    terminalManager.focus(sessionId);

    return () => {
      terminalManager.detach(sessionId);
    };
  }, [sessionId]);

  // Theme sync
  useEffect(() => {
    terminalManager.setTheme(isDarkMode);
  }, [isDarkMode]);

  // Font sync
  useEffect(() => {
    terminalManager.setFontFamily(
      resolveTerminalFontFamily(terminalFont, terminalCustomFontFamily),
    );
  }, [terminalFont, terminalCustomFontFamily]);

  // GPU rendering sync
  useEffect(() => {
    terminalManager.setUseWebgl(terminalGpuRendering);
  }, [terminalGpuRendering]);

  // Subscribe to shell data + exit events via the host shell client.
  useEffect(() => {
    if (!sessionId) return;
    const dataSub = shellClient.onData(sessionId, (event) => {
      terminalManager.writeData(event.sessionId, event.data);
    });
    const exitSub = shellClient.onExit(sessionId, (event) => {
      terminalManager.handleExit(event.sessionId, event.exitCode ?? undefined);
    });
    return () => {
      dataSub.unsubscribe();
      exitSub.unsubscribe();
    };
  }, [sessionId, shellClient]);

  // Event callbacks
  useEffect(() => {
    const offReady = terminalManager.on("ready", ({ sessionId: id }) => {
      if (id === sessionId) {
        onReady?.();
      }
    });

    const offExit = terminalManager.on(
      "exit",
      ({ sessionId: id, exitCode }) => {
        if (id === sessionId) {
          onExit?.(exitCode);
        }
      },
    );

    return () => {
      offReady();
      offExit();
    };
  }, [sessionId, onReady, onExit]);

  // mousedown so the xterm textarea is focused before the browser's native focus shift, not after.
  const handleMouseDown = useCallback(() => {
    terminalManager.focus(sessionId);
  }, [sessionId]);

  return (
    <Box onMouseDown={handleMouseDown} className="relative h-full p-3">
      <div ref={terminalRef} className="h-full w-full" />
      <style>
        {`
          .xterm {
            background-color: transparent !important;
          }
          .xterm .xterm-viewport {
            background-color: transparent !important;
          }
          .xterm .xterm-viewport::-webkit-scrollbar {
            display: none;
          }
          .xterm .xterm-viewport {
            scrollbar-width: none;
          }
        `}
      </style>
    </Box>
  );
}
