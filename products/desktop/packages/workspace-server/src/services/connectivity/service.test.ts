import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectivityEvent } from "./schemas";
import { ConnectivityService } from "./service";

const mockFetch = vi.hoisted(() => vi.fn());

const ok = (status = 200) => ({ ok: true, status });
const notOk = (status = 500) => ({ ok: false, status });

describe("ConnectivityService", () => {
  let service: ConnectivityService | undefined;

  beforeEach(() => {
    vi.clearAllMocks();
    vi.useFakeTimers();
    mockFetch.mockResolvedValue(ok());
    vi.stubGlobal("fetch", mockFetch);
  });

  afterEach(() => {
    service?.stop();
    service = undefined;
    vi.useRealTimers();
    vi.unstubAllGlobals();
  });

  describe("initial check", () => {
    it("goes online after a successful HEAD check", async () => {
      mockFetch.mockResolvedValue(ok(204));

      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);

      expect(service.getStatus()).toEqual({ isOnline: true });
      expect(mockFetch).toHaveBeenCalledWith(
        "https://www.google.com/generate_204",
        expect.objectContaining({ method: "HEAD" }),
      );
    });

    it("stays online after a single failed check (requires confirmation)", async () => {
      mockFetch.mockImplementation(() => {
        throw new Error("offline");
      });

      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);

      // One dropped probe is a transient blip, not an outage.
      expect(service.getStatus()).toEqual({ isOnline: true });
    });

    it("goes offline only after consecutive failed checks", async () => {
      mockFetch.mockImplementation(() => {
        throw new Error("offline");
      });

      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0); // 1st failure
      expect(service.getStatus()).toEqual({ isOnline: true });

      await vi.advanceTimersByTimeAsync(3000); // 2nd failure -> confirmed offline
      expect(service.getStatus()).toEqual({ isOnline: false });
    });
  });

  describe("checkNow", () => {
    it("returns online when HEAD succeeds", async () => {
      mockFetch.mockResolvedValue(ok(204));
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);

      const result = await service.checkNow();
      expect(result).toEqual({ isOnline: true });
    });

    it("does not flip offline on a single failed check", async () => {
      mockFetch.mockResolvedValue(ok(204));
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);

      mockFetch.mockRejectedValue(new Error("Network error"));
      const result = await service.checkNow();
      expect(result).toEqual({ isOnline: true });
    });

    it("returns offline once failures reach the threshold", async () => {
      mockFetch.mockRejectedValue(new Error("Network error"));
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0); // 1st failure

      const result = await service.checkNow(); // 2nd failure -> offline
      expect(result).toEqual({ isOnline: false });
    });
  });

  describe("status change events", () => {
    it("emits when going offline after confirmation", async () => {
      mockFetch.mockResolvedValue(ok(204));
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);

      const handler = vi.fn();
      service.on(ConnectivityEvent.StatusChange, handler);

      mockFetch.mockRejectedValue(new Error("offline"));
      await vi.advanceTimersByTimeAsync(30_000); // 1st failure at the healthy cadence
      await vi.advanceTimersByTimeAsync(3000); // fast recheck confirms offline

      expect(handler).toHaveBeenCalledWith({ isOnline: false });
      expect(handler).toHaveBeenCalledTimes(1);
    });

    it("does not emit on a single transient failure", async () => {
      mockFetch.mockResolvedValue(ok(204));
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);

      const handler = vi.fn();
      service.on(ConnectivityEvent.StatusChange, handler);

      mockFetch.mockRejectedValue(new Error("offline"));
      await vi.advanceTimersByTimeAsync(30_000); // one failed poll only

      expect(handler).not.toHaveBeenCalled();
    });

    it("emits when coming back online", async () => {
      mockFetch.mockRejectedValue(new Error("offline"));
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0); // 1st failure
      await vi.advanceTimersByTimeAsync(3000); // 2nd failure -> offline
      expect(service.getStatus()).toEqual({ isOnline: false });

      const handler = vi.fn();
      service.on(ConnectivityEvent.StatusChange, handler);

      mockFetch.mockResolvedValue(ok(204));
      await vi.advanceTimersByTimeAsync(3000); // recovery is instant

      expect(handler).toHaveBeenCalledWith({ isOnline: true });
    });

    it("does not emit when status is unchanged", async () => {
      mockFetch.mockResolvedValue(ok(204));
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);

      const handler = vi.fn();
      service.on(ConnectivityEvent.StatusChange, handler);

      await vi.advanceTimersByTimeAsync(3000);

      expect(handler).not.toHaveBeenCalled();
    });
  });

  describe("HTTP verification", () => {
    it("accepts 204 status as success", async () => {
      mockFetch.mockResolvedValue({ ok: false, status: 204 });
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);

      const result = await service.checkNow();
      expect(result).toEqual({ isOnline: true });
    });

    it("accepts 200 status as success", async () => {
      mockFetch.mockResolvedValue(ok(200));
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);

      const result = await service.checkNow();
      expect(result).toEqual({ isOnline: true });
    });

    it("treats a non-ok non-204 response as a failed probe", async () => {
      mockFetch.mockResolvedValue(notOk(500));
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0); // 1st failure

      const result = await service.checkNow(); // 2nd failure -> offline
      expect(result).toEqual({ isOnline: false });
    });
  });

  describe("multi-endpoint probing", () => {
    it("stays online when at least one host is reachable", async () => {
      // Google is blocked, Cloudflare answers.
      mockFetch.mockImplementation((url: string) =>
        url.includes("google")
          ? Promise.reject(new Error("blocked"))
          : Promise.resolve(ok(204)),
      );

      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);
      await vi.advanceTimersByTimeAsync(3000);

      const result = await service.checkNow();
      expect(result).toEqual({ isOnline: true });
    });

    it("short-circuits after the first reachable host", async () => {
      mockFetch.mockResolvedValue(ok(204));
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);

      expect(mockFetch).toHaveBeenCalledTimes(1);
      expect(mockFetch).toHaveBeenCalledWith(
        "https://www.google.com/generate_204",
        expect.objectContaining({ method: "HEAD" }),
      );
    });

    it("goes offline only when every host fails", async () => {
      mockFetch.mockRejectedValue(new Error("blocked"));

      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0); // 1st failure
      await vi.advanceTimersByTimeAsync(3000); // 2nd failure -> offline

      expect(service.getStatus()).toEqual({ isOnline: false });
    });
  });

  describe("polling", () => {
    it("polls periodically after construction", async () => {
      mockFetch.mockResolvedValue(ok(204));
      service = new ConnectivityService();
      await vi.advanceTimersByTimeAsync(0);

      const callsAfterInit = mockFetch.mock.calls.length;

      await vi.advanceTimersByTimeAsync(30_000);
      expect(mockFetch.mock.calls.length).toBeGreaterThan(callsAfterInit);
    });
  });
});
