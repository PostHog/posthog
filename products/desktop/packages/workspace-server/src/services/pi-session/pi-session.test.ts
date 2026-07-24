import { describe, expect, it } from "vitest";
import { selectPiPoolEvictionCandidate } from "./pi-session";

describe("selectPiPoolEvictionCandidate", () => {
  it("selects the least recently used idle session", () => {
    expect(
      selectPiPoolEvictionCandidate([
        { taskId: "recent", state: "idle", lastUsedAt: 30 },
        { taskId: "oldest", state: "idle", lastUsedAt: 10 },
        { taskId: "middle", state: "idle", lastUsedAt: 20 },
      ]),
    ).toBe("oldest");
  });

  it("pins streaming, starting, and protected sessions", () => {
    expect(
      selectPiPoolEvictionCandidate(
        [
          { taskId: "streaming", state: "streaming", lastUsedAt: 1 },
          { taskId: "starting", state: "starting", lastUsedAt: 2 },
          { taskId: "protected", state: "idle", lastUsedAt: 3 },
          { taskId: "evictable", state: "idle", lastUsedAt: 4 },
        ],
        "protected",
      ),
    ).toBe("evictable");
  });

  it("returns null when every session is pinned", () => {
    expect(
      selectPiPoolEvictionCandidate([
        { taskId: "streaming", state: "streaming", lastUsedAt: 1 },
        { taskId: "starting", state: "starting", lastUsedAt: 2 },
      ]),
    ).toBeNull();
  });
});
