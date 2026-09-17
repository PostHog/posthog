import { useDroppable } from "@dnd-kit/react";
import { cn } from "@posthog/quill";
import type { CSSProperties } from "react";
import type { TileEdge } from "./tileLayout";

export const TILE_DROP_TYPE = "tile-drop";

export interface TileDropData {
  type: typeof TILE_DROP_TYPE;
  tabId: string;
  edge: TileEdge;
}

export function isTileDropData(data: unknown): data is TileDropData {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as { type?: unknown }).type === TILE_DROP_TYPE
  );
}

const BAND = "30%";

const HIT_AREAS: Record<TileEdge, CSSProperties> = {
  left: { top: 0, bottom: 0, left: 0, width: BAND },
  right: { top: 0, bottom: 0, right: 0, width: BAND },
  top: { top: 0, left: BAND, right: BAND, height: BAND },
  bottom: { bottom: 0, left: BAND, right: BAND, height: BAND },
};

const PREVIEWS: Record<TileEdge, string> = {
  left: "inset-y-0 left-0 w-1/2",
  right: "inset-y-0 right-0 w-1/2",
  top: "inset-x-0 top-0 h-1/2",
  bottom: "inset-x-0 bottom-0 h-1/2",
};

function EdgeZone({
  tabId,
  edge,
  disabled,
}: {
  tabId: string;
  edge: TileEdge;
  disabled: boolean;
}) {
  const data: TileDropData = { type: TILE_DROP_TYPE, tabId, edge };
  const { ref, isDropTarget } = useDroppable({
    id: `tile-drop-${tabId}-${edge}`,
    data,
    disabled,
  });
  return (
    <>
      <div
        ref={ref}
        className="pointer-events-auto absolute"
        style={HIT_AREAS[edge]}
      />
      {isDropTarget && (
        <div
          aria-hidden
          className={cn(
            "pointer-events-none absolute rounded-sm border-2 border-accent-8 bg-(--accent-a4)",
            PREVIEWS[edge],
          )}
        />
      )}
    </>
  );
}

export function TileDropZones({
  tabId,
  disabled = false,
}: {
  tabId: string;
  disabled?: boolean;
}) {
  return (
    <div className="pointer-events-none absolute inset-0 z-50">
      {(Object.keys(HIT_AREAS) as TileEdge[]).map((edge) => (
        <EdgeZone key={edge} tabId={tabId} edge={edge} disabled={disabled} />
      ))}
    </div>
  );
}
