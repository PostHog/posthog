import type { ReactNode } from "react";

export interface SidebarItemAction {
  icon: ReactNode;
  onClick: () => void;
  alwaysVisible?: boolean;
}
