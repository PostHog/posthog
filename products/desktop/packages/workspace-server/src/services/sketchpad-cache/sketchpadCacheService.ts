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

interface WriteEntry {
  pending?: SketchpadCachePayload;
  inFlight: Promise<void>;
}

@injectable()
export class SketchpadCacheServiceImpl implements SketchpadCacheService {
  private readonly writes = new Map<string, WriteEntry>();

  write(payload: SketchpadCachePayload): Promise<void> {
    const filePath = sketchpadCacheFilePath(os.homedir(), payload.sketchpadId);
    const existing = this.writes.get(filePath);
    if (existing) {
      existing.pending = payload;
      return existing.inFlight;
    }
    const entry: WriteEntry = { inFlight: Promise.resolve() };
    this.writes.set(filePath, entry);
    entry.inFlight = this.drain(filePath, payload, entry);
    return entry.inFlight;
  }

  private async drain(
    filePath: string,
    initial: SketchpadCachePayload,
    entry: WriteEntry,
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
        payload = entry.pending;
        entry.pending = undefined;
      }
    } catch (error) {
      entry.pending = undefined;
      throw error;
    } finally {
      this.writes.delete(filePath);
      if (tmpPath !== undefined) await fs.rm(tmpPath, { force: true });
    }
  }
}
