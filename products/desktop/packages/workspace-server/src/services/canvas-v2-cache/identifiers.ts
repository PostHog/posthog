import type { CanvasV2CachePayload } from "@posthog/shared";

export const CANVAS_V2_CACHE_SERVICE = Symbol.for(
  "posthog.workspace.canvasV2Cache",
);

export interface CanvasV2CacheService {
  /**
   * Writes the board cache file the agent read tools load. The write is
   * atomic, so a tool never reads a half-written file.
   */
  write(boardId: string, payload: CanvasV2CachePayload): Promise<void>;
}
