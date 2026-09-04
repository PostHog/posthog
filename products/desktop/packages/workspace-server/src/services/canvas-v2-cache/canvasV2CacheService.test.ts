import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import { canvasV2CacheFilePath, emptyCanvasV2Snapshot } from "@posthog/shared";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { CanvasV2CacheServiceImpl } from "./canvasV2CacheService";

vi.mock("node:os", async (importOriginal) => ({
  ...(await importOriginal<typeof os>()),
  homedir: vi.fn(),
}));

vi.mock("node:fs/promises", async (importOriginal) => {
  const actual = await importOriginal<typeof fs>();
  return {
    ...actual,
    writeFile: vi.fn(actual.writeFile),
    rename: vi.fn(actual.rename),
  };
});

function payload(boardId: string, headSeq: number) {
  return {
    boardId,
    headSeq,
    name: `Board ${headSeq}`,
    snapshot: emptyCanvasV2Snapshot(),
  };
}

describe("CanvasV2CacheService", () => {
  let homeDir: string;
  beforeEach(async () => {
    vi.clearAllMocks();
    homeDir = await fs.mkdtemp(path.join(os.tmpdir(), "canvas-cache-test-"));
    vi.mocked(os.homedir).mockReturnValue(homeDir);
  });
  afterEach(async () => {
    vi.restoreAllMocks();
    await fs.rm(homeDir, { recursive: true, force: true });
  });

  it("keeps the latest queued board and lets other boards write independently", async () => {
    let release!: () => void;
    let entered!: () => void;
    const blocked = new Promise<void>((resolve) => {
      release = resolve;
    });
    const started = new Promise<void>((resolve) => {
      entered = resolve;
    });
    const { writeFile } = await vi.importActual<typeof fs>("node:fs/promises");
    vi.mocked(fs.writeFile).mockImplementationOnce(async (...args) => {
      entered();
      await blocked;
      return writeFile(...args);
    });
    vi.spyOn(Date, "now").mockReturnValue(1);
    const service = new CanvasV2CacheServiceImpl();
    const first = service.write("board", payload("board", 1));
    await started;
    const second = service.write("board", payload("board", 2));
    const last = service.write("board", payload("board", 3));
    const results = Promise.allSettled([first, second, last]);
    await service.write("other", payload("other", 1));
    release();

    expect(await results).toEqual(
      Array.from({ length: 3 }, () => ({
        status: "fulfilled",
        value: undefined,
      })),
    );
    expect(
      JSON.parse(
        await fs.readFile(canvasV2CacheFilePath(homeDir, "board"), "utf8"),
      ),
    ).toEqual(payload("board", 3));
    expect(fs.writeFile).toHaveBeenCalledTimes(3);
  });

  it.each(["writeFile", "rename"] as const)(
    "cleans up and accepts another write after %s fails",
    async (method) => {
      const service = new CanvasV2CacheServiceImpl();
      vi.mocked(
        method === "writeFile" ? fs.writeFile : fs.rename,
      ).mockRejectedValueOnce(new Error("Disk write failed"));
      await expect(service.write("board", payload("board", 1))).rejects.toThrow(
        "Disk write failed",
      );

      await service.write("board", payload("board", 2));

      const filePath = canvasV2CacheFilePath(homeDir, "board");
      expect(JSON.parse(await fs.readFile(filePath, "utf8"))).toEqual(
        payload("board", 2),
      );
      expect(await fs.readdir(path.dirname(filePath))).toEqual(["board.json"]);
    },
  );
});
