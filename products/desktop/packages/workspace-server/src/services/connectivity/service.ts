import { TypedEventEmitter } from "@posthog/shared";
import { injectable } from "inversify";
import {
  ConnectivityEvent,
  type ConnectivityEvents,
  type ConnectivityStatusOutput,
} from "./schemas";

const CHECK_URLS = [
  "https://www.google.com/generate_204",
  "https://www.cloudflare.com/cdn-cgi/trace",
];
const CHECK_TIMEOUT_MS = 5_000;
const OFFLINE_CONFIRM_THRESHOLD = 2;
const MIN_POLL_INTERVAL_MS = 3_000;
const MAX_POLL_INTERVAL_MS = 10_000;
const ONLINE_POLL_INTERVAL_MS = 30_000;
const OFFLINE_BACKOFF_MULTIPLIER = 1.5;

@injectable()
export class ConnectivityService extends TypedEventEmitter<ConnectivityEvents> {
  private isOnline = true;
  private pollTimeoutId: ReturnType<typeof setTimeout> | null = null;
  private offlinePollAttempt = 0;
  private consecutiveFailures = 0;

  constructor() {
    super();
    this.setMaxListeners(0);
    void this.checkConnectivity().finally(() => this.startPolling());
  }

  getStatus(): ConnectivityStatusOutput {
    return { isOnline: this.isOnline };
  }

  async checkNow(): Promise<ConnectivityStatusOutput> {
    await this.checkConnectivity();
    return { isOnline: this.isOnline };
  }

  stop(): void {
    if (this.pollTimeoutId) {
      clearTimeout(this.pollTimeoutId);
      this.pollTimeoutId = null;
    }
  }

  statusChangeEvents(
    signal: AbortSignal | undefined,
  ): AsyncIterable<ConnectivityStatusOutput> {
    return this.toIterable(ConnectivityEvent.StatusChange, { signal });
  }

  private setOnline(online: boolean): void {
    if (this.isOnline === online) return;
    this.isOnline = online;
    this.emit(ConnectivityEvent.StatusChange, { isOnline: online });
    this.offlinePollAttempt = 0;
  }

  private async checkConnectivity(): Promise<void> {
    const verified = await this.verifyWithHttp();

    if (verified) {
      this.consecutiveFailures = 0;
      this.setOnline(true);
      return;
    }

    this.consecutiveFailures++;
    if (this.consecutiveFailures >= OFFLINE_CONFIRM_THRESHOLD) {
      this.setOnline(false);
    }
  }

  private async verifyWithHttp(): Promise<boolean> {
    // Sequential on purpose: one request per check in the common case, at the
    // cost of up to CHECK_TIMEOUT_MS extra latency when the first host is blocked.
    for (const url of CHECK_URLS) {
      try {
        await this.probe(url);
        return true;
      } catch {}
    }
    return false;
  }

  private async probe(url: string): Promise<void> {
    const response = await fetch(url, {
      method: "HEAD",
      signal: AbortSignal.timeout(CHECK_TIMEOUT_MS),
    });
    if (!(response.ok || response.status === 204)) {
      throw new Error(`Unexpected status ${response.status} from ${url}`);
    }
  }

  private startPolling(): void {
    if (this.pollTimeoutId) return;
    this.offlinePollAttempt = 0;
    this.schedulePoll();
  }

  private schedulePoll(): void {
    // Poll rarely while healthy, quickly while confirming a suspected outage.
    const interval = this.isOnline
      ? this.consecutiveFailures > 0
        ? MIN_POLL_INTERVAL_MS
        : ONLINE_POLL_INTERVAL_MS
      : Math.min(
          MIN_POLL_INTERVAL_MS *
            OFFLINE_BACKOFF_MULTIPLIER ** this.offlinePollAttempt,
          MAX_POLL_INTERVAL_MS,
        );

    this.pollTimeoutId = setTimeout(async () => {
      this.pollTimeoutId = null;
      const wasOffline = !this.isOnline;
      await this.checkConnectivity();
      if (!this.isOnline && wasOffline) {
        this.offlinePollAttempt++;
      }
      this.schedulePoll();
    }, interval);
    this.pollTimeoutId.unref?.();
  }
}
