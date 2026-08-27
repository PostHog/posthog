import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ReleaseFeedService } from "./release-feed";

const sampleFeed = {
  releases: [
    {
      version: "1.2.0",
      name: "v1.2.0",
      notes: "## Notes\n- thing",
      date: "2026-06-20T00:00:00Z",
      isPrerelease: false,
      htmlUrl: "https://github.com/PostHog/code/releases/tag/v1.2.0",
    },
    {
      version: "1.1.0",
      name: "v1.1.0",
      notes: "",
      date: "2026-06-10T00:00:00Z",
      isPrerelease: true,
      htmlUrl: "https://github.com/PostHog/code/releases/tag/v1.1.0",
    },
  ],
};

describe("ReleaseFeedService", () => {
  let fetchMock: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    fetchMock = vi.fn(async () => ({
      ok: true,
      status: 200,
      json: async () => sampleFeed,
    }));
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns the parsed feed", async () => {
    const service = new ReleaseFeedService();
    const { releases } = await service.listReleases();

    expect(releases).toHaveLength(2);
    expect(releases[0]).toEqual(sampleFeed.releases[0]);
  });

  it("rejects a malformed feed payload", async () => {
    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({ releases: [{ version: 123 }] }),
    });
    const service = new ReleaseFeedService();
    await expect(service.listReleases()).rejects.toThrow();
  });

  it.each([
    { expectVersion: undefined, expectedFetches: 1 },
    { expectVersion: "1.2.0", expectedFetches: 1 },
    { expectVersion: "1.3.0", expectedFetches: 2 },
  ])(
    "a fresh cache is a hit for expectVersion $expectVersion only when it contains it ($expectedFetches fetches)",
    async ({ expectVersion, expectedFetches }) => {
      const service = new ReleaseFeedService();
      await service.listReleases();
      await service.listReleases(expectVersion);
      expect(fetchMock).toHaveBeenCalledTimes(expectedFetches);
    },
  );

  it("caches the refetched list once it contains the expected version", async () => {
    const service = new ReleaseFeedService();
    await service.listReleases();

    fetchMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: async () => ({
        releases: [
          {
            version: "1.3.0",
            name: "v1.3.0",
            notes: "new",
            date: "2026-06-30T00:00:00Z",
            isPrerelease: false,
            htmlUrl: "https://github.com/PostHog/code/releases/tag/v1.3.0",
          },
          ...sampleFeed.releases,
        ],
      }),
    });
    const second = await service.listReleases("1.3.0");
    expect(second.releases[0].version).toBe("1.3.0");

    const third = await service.listReleases("1.3.0");
    expect(third).toEqual(second);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("dedupes concurrent cache misses into a single fetch", async () => {
    const service = new ReleaseFeedService();
    const [first, second] = await Promise.all([
      service.listReleases(),
      service.listReleases("1.3.0"),
    ]);

    expect(first).toEqual(second);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("concurrent callers both reject when the shared fetch fails, and inFlight is cleared so subsequent calls retry", async () => {
    fetchMock.mockRejectedValueOnce(new Error("network error"));
    const service = new ReleaseFeedService();

    const [result1, result2] = await Promise.allSettled([
      service.listReleases(),
      service.listReleases("1.2.0"),
    ]);

    expect(result1.status).toBe("rejected");
    expect(result2.status).toBe("rejected");
    // inFlight must be cleared so the next call retries rather than hanging
    await service.listReleases();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("waits out a cooldown before refetching a still-missing version", async () => {
    const nowSpy = vi.spyOn(Date, "now").mockReturnValue(0);
    const service = new ReleaseFeedService();
    await service.listReleases("9.9.9");
    await service.listReleases("9.9.9");
    expect(fetchMock).toHaveBeenCalledTimes(1);

    nowSpy.mockReturnValue(61_000);
    await service.listReleases("9.9.9");
    expect(fetchMock).toHaveBeenCalledTimes(2);
    nowSpy.mockRestore();
  });

  it("serves stale cache when a version-miss refetch fails, without retrying within the cooldown", async () => {
    const nowSpy = vi.spyOn(Date, "now").mockReturnValue(0);
    const service = new ReleaseFeedService();
    const first = await service.listReleases();

    fetchMock.mockResolvedValueOnce({ ok: false, status: 500 });
    const second = await service.listReleases("1.3.0");
    expect(second).toEqual(first);
    expect(fetchMock).toHaveBeenCalledTimes(2);

    const third = await service.listReleases("1.3.0");
    expect(third).toEqual(first);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    nowSpy.mockRestore();
  });

  it("throws on non-ok responses", async () => {
    fetchMock.mockResolvedValueOnce({ ok: false, status: 503 });
    const service = new ReleaseFeedService();
    await expect(service.listReleases()).rejects.toThrow();
  });

  it("serves stale cache when a later refetch fails", async () => {
    const nowSpy = vi.spyOn(Date, "now").mockReturnValue(0);
    const service = new ReleaseFeedService();
    const first = await service.listReleases();

    nowSpy.mockReturnValue(11 * 60_000);
    fetchMock.mockResolvedValueOnce({ ok: false, status: 500 });
    const second = await service.listReleases();

    expect(second).toEqual(first);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    nowSpy.mockRestore();
  });
});
