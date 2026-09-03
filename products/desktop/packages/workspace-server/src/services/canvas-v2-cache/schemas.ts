import { canvasV2SnapshotSchema } from "@posthog/shared";
import { z } from "zod";

export const writeCanvasV2CacheInput = z.object({
  boardId: z.string().min(1),
  payload: z.object({
    boardId: z.string().min(1),
    name: z.string(),
    headSeq: z.number().int(),
    snapshot: canvasV2SnapshotSchema,
  }),
});
