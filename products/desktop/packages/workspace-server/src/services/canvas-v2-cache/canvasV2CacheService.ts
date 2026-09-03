import * as fs from "node:fs/promises";
import * as os from "node:os";
import * as path from "node:path";
import {
  type CanvasV2CachePayload,
  canvasV2CacheFilePath,
} from "@posthog/shared";
import { injectable } from "inversify";
import type { CanvasV2CacheService } from "./identifiers";

@injectable()
export class CanvasV2CacheServiceImpl implements CanvasV2CacheService {
  async write(boardId: string, payload: CanvasV2CachePayload): Promise<void> {
    const filePath = canvasV2CacheFilePath(os.homedir(), boardId);
    await fs.mkdir(path.dirname(filePath), { recursive: true });
    const tmpPath = `${filePath}.tmp.${Date.now()}`;
    await fs.writeFile(tmpPath, `${JSON.stringify(payload, null, 2)}\n`);
    await fs.rename(tmpPath, filePath);
  }
}
