import type { DashboardRecord } from "@posthog/core/canvas/dashboardSchemas";
import type { SketchpadSummary } from "@posthog/shared";
import { useSketchpadsFlag } from "@posthog/ui/features/feature-flags/useSketchpadsFlag";
import { useSketchpads } from "@posthog/ui/features/sketchpad/hooks/useSketchpads";
import { useMemo } from "react";

const NO_RECORDS: DashboardRecord[] = [];

export function sketchpadAsCanvas(board: SketchpadSummary): DashboardRecord {
  return {
    id: board.id,
    channelId: board.channelId,
    name: board.name,
    kind: "freeform",
    description: "",
    templateId: "freeform",
    canvasType: "sketchpad",
    createdBy: board.createdBy?.userName,
    createdByUuid: board.createdBy?.userUuid,
    createdByEmail: board.createdBy?.userEmail,
    lastActor: board.lastActor
      ? {
          name: board.lastActor.userName,
          uuid: board.lastActor.userUuid,
          email: board.lastActor.userEmail,
        }
      : undefined,
    pinnedAt: board.pinned ? new Date(board.updatedAt).getTime() : undefined,
    createdAt: new Date(board.createdAt).getTime(),
    updatedAt: new Date(board.updatedAt).getTime(),
  };
}

<<<<<<< HEAD
function useSketchpadsAsCanvases(
  channelId: string | undefined,
  requested: boolean,
): DashboardRecord[] {
  const enabled = useSketchpadsFlag() && requested;
  const { boards } = useSketchpads(channelId, enabled);
  return useMemo(
    () =>
      enabled && boards.length > 0 ? boards.map(sketchpadAsCanvas) : NO_RECORDS,
    [boards, enabled],
  );
}

export function useSpaceSketchpadsAsCanvases(
  channelId: string | undefined,
): DashboardRecord[] {
  return useSketchpadsAsCanvases(channelId, Boolean(channelId));
}

export function useAllSketchpadsAsCanvases(): DashboardRecord[] {
  return useSketchpadsAsCanvases(undefined, true);
=======
export function useSpaceSketchpadsAsCanvases(
  channelId: string | undefined,
): DashboardRecord[] {
  const enabled = useSketchpadsFlag();
  const { boards } = useSketchpads(channelId, enabled && !!channelId);
  return useMemo(
    () => (enabled && channelId ? boards.map(sketchpadAsCanvas) : NO_RECORDS),
    [boards, channelId, enabled],
  );
}

export function useAllSketchpadsAsCanvases(): DashboardRecord[] {
  const enabled = useSketchpadsFlag();
  const { boards } = useSketchpads(undefined, enabled);
  return useMemo(
    () => (enabled ? boards.map(sketchpadAsCanvas) : NO_RECORDS),
    [boards, enabled],
  );
>>>>>>> e14cb962164 (feat(desktop): add sketchpad UI runtime, library, and sync hooks)
}
