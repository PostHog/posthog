export const TILE_TAB_DRAG_TYPE = "tile-tab";

export interface TileTabDragData {
  type: typeof TILE_TAB_DRAG_TYPE;
  tabId: string;
}

export function isTileTabDragData(data: unknown): data is TileTabDragData {
  return (
    typeof data === "object" &&
    data !== null &&
    (data as { type?: unknown }).type === TILE_TAB_DRAG_TYPE
  );
}
