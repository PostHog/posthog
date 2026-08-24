import type { ReactNode } from "react";

export type SortMode = "updated" | "created";

export interface SidebarItemAction {
  icon: ReactNode;
  onClick: () => void;
  alwaysVisible?: boolean;
}
