import { randomUUID } from "node:crypto";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import {
  type CanvasV2CachePayload,
  canvasV2CacheFilePath,
} from "@posthog/shared";
import { injectable } from "inversify";
import type { CanvasV2CacheService } from "./identifiers";

interface WriteState {
  pending?: CanvasV2CachePayload;
}

@injectable()
export class CanvasV2CacheServiceImpl implements CanvasV2CacheService {
  private readonly writes = new Map<
    string,
    { state: WriteState; inFlight: Promise<void> }
  >();

  write(boardId: string, payload: CanvasV2CachePayload): Promise<void> {
    const filePath = canvasV2CacheFilePath(os.homedir(), boardId);
    const existing = this.writes.get(filePath);
    if (existing) {
      existing.state.pending = payload;
      return existing.inFlight;
    }
    const state: WriteState = {};
    const inFlight = this.drain(filePath, payload, state);
    this.writes.set(filePath, { state, inFlight });
    return inFlight;
  }

  private async drain(
    filePath: string,
    initial: CanvasV2CachePayload,
    state: WriteState,
  ): Promise<void> {
    let tmpPath: string | undefined;
    try {
      await fs.mkdir(path.dirname(filePath), { recursive: true });
      let payload: CanvasV2CachePayload | undefined = initial;
      while (payload !== undefined) {
        tmpPath = `${filePath}.tmp.${randomUUID()}`;
        await fs.writeFile(tmpPath, `${JSON.stringify(payload)}\n`);
        await fs.rename(tmpPath, filePath);
        tmpPath = undefined;
        payload = state.pending;
        state.pending = undefined;
      }
    } finally {
      this.writes.delete(filePath);
      if (tmpPath !== undefined) await fs.rm(tmpPath, { force: true });
    }
  }
}
