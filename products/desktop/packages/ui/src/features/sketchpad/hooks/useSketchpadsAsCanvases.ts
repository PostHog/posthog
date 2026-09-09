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
}
