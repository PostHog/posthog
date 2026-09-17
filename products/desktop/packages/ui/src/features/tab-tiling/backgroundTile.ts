import { createContext, useContext } from "react";

/**
 * True for a page mounted in a tile whose tab is not the active one. Such a
 * page is visible but does not own the shared header or the global shortcuts;
 * those belong to the active tab's page.
 */
const BackgroundTileContext = createContext(false);

export const BackgroundTileProvider = BackgroundTileContext.Provider;

export function useInBackgroundTile(): boolean {
  return useContext(BackgroundTileContext);
}
