import { createContext, useContext } from "react";

const BackgroundTileContext = createContext(false);

export const BackgroundTileProvider = BackgroundTileContext.Provider;

export function useInBackgroundTile(): boolean {
  return useContext(BackgroundTileContext);
}
