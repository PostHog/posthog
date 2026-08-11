import "reflect-metadata";
import dns from "node:dns";
import net from "node:net";
import { serve } from "@hono/node-server";
import { createApp } from "./app";
import { container } from "./di/container";
import {
  CONNECTIVITY_SERVICE,
  ENVIRONMENT_SERVICE,
  FOCUS_SERVICE,
  FOCUS_SYNC_SERVICE,
  FS_SERVICE,
  GIT_SERVICE,
  LOCAL_LOGS_SERVICE,
  WATCHER_SERVICE,
} from "./di/tokens";
import { removeLegacyNodeShimDirs } from "./services/agent/legacy-node-shim";
import type { ConnectivityService } from "./services/connectivity/service";
import type { EnvironmentService } from "./services/environment/service";
import type { FocusService } from "./services/focus/service";
import type { FocusSyncService } from "./services/focus/sync-service";
import type { FsService } from "./services/fs/service";
import type { GitService } from "./services/git/service";
import type { LocalLogsService } from "./services/local-logs/service";
import type { WatcherService } from "./services/watcher/service";
import { createAppRouter } from "./trpc";

// Prefer IPv4 and disable "Happy Eyeballs" (mirrors apps/code main bootstrap).
// This child makes all outbound HTTPS to PostHog/the gateway; its many-address
// ELB times out when IPv6 is unreachable (e.g. Tailscale).
dns.setDefaultResultOrder("ipv4first");
net.setDefaultAutoSelectFamily(false);

const SHUTDOWN_GRACE_MS = 3_000;
const WATCHDOG_INTERVAL_MS = 2_000;

function isParentAlive(parentPid: number): boolean {
  try {
    process.kill(parentPid, 0);
    return process.ppid === parentPid;
  } catch {
    return false;
  }
}

const sharedSecret = process.env.WORKSPACE_SERVER_SECRET;
const port = Number(process.env.WORKSPACE_SERVER_PORT);
const parentPid = Number(process.env.WORKSPACE_SERVER_PARENT_PID);

if (!sharedSecret || !Number.isInteger(port) || port <= 0 || port > 65_535) {
  process.stderr.write(
    "[workspace-server] missing or invalid WORKSPACE_SERVER_SECRET / WORKSPACE_SERVER_PORT\n",
  );
  process.exit(2);
}

const shimCleanup = removeLegacyNodeShimDirs();
for (const dir of shimCleanup.removed) {
  process.stdout.write(
    `[workspace-server] removed legacy node shim dir ${dir}\n`,
  );
}
for (const dir of shimCleanup.failed) {
  process.stderr.write(
    `[workspace-server] failed to remove legacy node shim dir ${dir}\n`,
  );
}

const router = createAppRouter({
  focusService: container.get<FocusService>(FOCUS_SERVICE),
  focusSyncService: container.get<FocusSyncService>(FOCUS_SYNC_SERVICE),
  gitService: container.get<GitService>(GIT_SERVICE),
  fsService: container.get<FsService>(FS_SERVICE),
  watcherService: container.get<WatcherService>(WATCHER_SERVICE),
  localLogsService: container.get<LocalLogsService>(LOCAL_LOGS_SERVICE),
  connectivityService: container.get<ConnectivityService>(CONNECTIVITY_SERVICE),
  environmentService: container.get<EnvironmentService>(ENVIRONMENT_SERVICE),
});
const app = createApp({ sharedSecret, router });

let server: ReturnType<typeof serve> | null = null;
let shuttingDown = false;
const shutdown = (reason: string) => {
  if (shuttingDown) return;
  shuttingDown = true;
  process.stdout.write(`[workspace-server] shutdown (${reason})\n`);
  if (!server) process.exit(0);
  server.close();
  setTimeout(() => process.exit(0), SHUTDOWN_GRACE_MS).unref();
};

process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));

if (Number.isInteger(parentPid) && parentPid > 1) {
  setInterval(() => {
    if (!isParentAlive(parentPid)) shutdown("parent-exit");
  }, WATCHDOG_INTERVAL_MS).unref();
}

server = serve({ fetch: app.fetch, port, hostname: "127.0.0.1" }, (info) => {
  process.stdout.write(
    `[workspace-server] listening on http://127.0.0.1:${info.port}\n`,
  );
});
