import type { SketchpadCachePayload } from "@posthog/shared";

export const SKETCHPAD_CACHE_SERVICE = Symbol.for(
  "posthog.workspace.sketchpadCache",
);

export interface SketchpadCacheService {
  write(payload: SketchpadCachePayload): Promise<void>;
}
