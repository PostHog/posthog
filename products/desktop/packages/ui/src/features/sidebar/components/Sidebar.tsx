import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { ResizableSidebar } from "@posthog/ui/primitives/ResizableSidebar";
import type React from "react";

export const Sidebar: React.FC<{ children: React.ReactNode }> = ({
  children,
}) => {
  const open = useSidebarStore((state) => state.open);
  const width = useSidebarStore((state) => state.width);
  const setWidth = useSidebarStore((state) => state.setWidth);
  const isResizing = useSidebarStore((state) => state.isResizing);
  const setIsResizing = useSidebarStore((state) => state.setIsResizing);

  return (
    <ResizableSidebar
      open={open}
      width={width}
      setWidth={setWidth}
      isResizing={isResizing}
      setIsResizing={setIsResizing}
      side="left"
    >
      {children}
    </ResizableSidebar>
  );
};
