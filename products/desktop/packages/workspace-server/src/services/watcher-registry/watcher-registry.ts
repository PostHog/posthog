import type * as watcher from "@parcel/watcher";
import {
  ROOT_LOGGER,
  type RootLogger,
  type ScopedLogger,
} from "@posthog/di/logger";
import { inject, injectable } from "inversify";

const UNSUBSCRIBE_TIMEOUT_MS = 2000;

@injectable()
export class WatcherRegistryService {
  private subscriptions = new Map<string, watcher.AsyncSubscription>();
  private _isShutdown = false;
  private readonly log: ScopedLogger;

  constructor(
    @inject(ROOT_LOGGER)
    logger: RootLogger,
  ) {
    this.log = logger.scope("watcher-registry");
  }

  get isShutdown(): boolean {
    return this._isShutdown;
  }

  register(id: string, subscription: watcher.AsyncSubscription): void {
    if (this._isShutdown) {
      this.log.warn(`Attempted to register watcher after shutdown: ${id}`);
      subscription.unsubscribe().catch((err) => {
        this.log.warn(`Failed to unsubscribe rejected watcher ${id}:`, {
          error: err,
        });
      });
      return;
    }

    if (this.subscriptions.has(id)) {
      const existing = this.subscriptions.get(id);
      existing?.unsubscribe().catch((err) => {
        this.log.warn(`Failed to unsubscribe replaced watcher ${id}:`, {
          error: err,
        });
      });
    }

    this.subscriptions.set(id, subscription);
  }

  async unregister(id: string): Promise<void> {
    const subscription = this.subscriptions.get(id);
    if (!subscription) return;

    this.subscriptions.delete(id);
    try {
      await subscription.unsubscribe();
      this.log.debug(`Unregistered watcher: ${id}`);
    } catch (err) {
      this.log.warn(`Failed to unsubscribe watcher ${id}:`, { error: err });
    }
  }

  async shutdownAll(): Promise<void> {
    if (this._isShutdown) {
      this.log.warn("shutdownAll called but already shutdown");
      return;
    }

    this._isShutdown = true;
    const count = this.subscriptions.size;

    if (count === 0) {
      this.log.info("No watchers to shutdown");
      return;
    }

    this.log.info(`Shutting down ${count} watchers`);

    const entries = Array.from(this.subscriptions.entries());
    this.subscriptions.clear();

    const results = await Promise.allSettled(
      entries.map(([id, sub]) => this.unsubscribeWithTimeout(id, sub)),
    );

    const failures = results.filter((r) => r.status === "rejected").length;
    const timeouts = results.filter(
      (r) => r.status === "fulfilled" && r.value === "timeout",
    ).length;

    if (failures > 0 || timeouts > 0) {
      this.log.warn(
        `Watcher shutdown: ${count - failures - timeouts} clean, ${timeouts} timed out, ${failures} failed`,
      );
    } else {
      this.log.info(`All ${count} watchers shutdown successfully`);
    }
  }

  private async unsubscribeWithTimeout(
    id: string,
    sub: watcher.AsyncSubscription,
  ): Promise<"ok" | "timeout"> {
    const timeoutPromise = new Promise<"timeout">((resolve) =>
      setTimeout(() => resolve("timeout"), UNSUBSCRIBE_TIMEOUT_MS),
    );

    const unsubPromise = sub
      .unsubscribe()
      .then(() => "ok" as const)
      .catch((err) => {
        this.log.warn(`Failed to unsubscribe watcher ${id}:`, { error: err });
        return "ok" as const;
      });

    const result = await Promise.race([unsubPromise, timeoutPromise]);

    if (result === "timeout") {
      this.log.warn(
        `Watcher ${id} unsubscribe timed out after ${UNSUBSCRIBE_TIMEOUT_MS}ms`,
      );
    } else {
      this.log.debug(`Shutdown watcher: ${id}`);
    }

    return result;
  }
}
