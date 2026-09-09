import { randomUUID } from "node:crypto";
import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import {
  type SketchpadCachePayload,
  sketchpadCacheFilePath,
} from "@posthog/shared";
import { injectable } from "inversify";
import type { SketchpadCacheService } from "./identifiers";

interface WriteState {
  pending?: SketchpadCachePayload;
}

@injectable()
export class SketchpadCacheServiceImpl implements SketchpadCacheService {
  private readonly writes = new Map<
    string,
    { state: WriteState; inFlight: Promise<void> }
  >();

  write(payload: SketchpadCachePayload): Promise<void> {
    const filePath = sketchpadCacheFilePath(os.homedir(), payload.sketchpadId);
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
    initial: SketchpadCachePayload,
    state: WriteState,
  ): Promise<void> {
    let tmpPath: string | undefined;
    try {
      await fs.mkdir(path.dirname(filePath), { recursive: true });
      let payload: SketchpadCachePayload | undefined = initial;
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
