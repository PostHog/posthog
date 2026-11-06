import { createContext, useContext } from "react";

const TileContext = createContext<{ focused: boolean } | null>(null);

export const TileProvider = TileContext.Provider;

export function useInTile(): boolean {
  return useContext(TileContext) !== null;
}

export function useInUnfocusedTile(): boolean {
  const tile = useContext(TileContext);
  return tile !== null && !tile.focused;
}
