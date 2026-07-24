import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import type React from "react";
import { KeyHint } from "./KeyHint";

interface TooltipProps {
  children: React.ReactNode;
  content: React.ReactNode;
  shortcut?: string;
  side?: "top" | "right" | "bottom" | "left";
  align?: "start" | "center" | "end";
  sideOffset?: number;
  delayDuration?: number;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function Tooltip({
  children,
  content,
  shortcut,
  side = "top",
  align = "center",
  sideOffset = 6,
  delayDuration = 200,
  open,
  defaultOpen,
  onOpenChange,
}: TooltipProps) {
  const isSimpleContent =
    typeof content === "string" || typeof content === "number";

  return (
    <TooltipPrimitive.Provider delayDuration={delayDuration}>
      <TooltipPrimitive.Root
        open={open}
        defaultOpen={defaultOpen}
        onOpenChange={onOpenChange}
      >
        <TooltipPrimitive.Trigger asChild>{children}</TooltipPrimitive.Trigger>
        <TooltipPrimitive.Portal>
          <TooltipPrimitive.Content
            side={side}
            align={align}
            sideOffset={sideOffset}
            className="dark flex items-center gap-[8px] rounded-[6px] border border-(--gray-4) bg-(--gray-2) px-[10px] py-[6px] text-(--gray-12) text-xs leading-[1.4]"
            style={{
              whiteSpace: isSimpleContent ? "nowrap" : "normal",
              boxShadow: "0 4px 12px rgba(0, 0, 0, 0.25)",
              zIndex: 9999,
              animationDuration: "150ms",
              animationTimingFunction: "ease-out",
              willChange: "transform, opacity",
            }}
          >
            {isSimpleContent ? <span>{content}</span> : content}
            {shortcut && <KeyHint className="text-xs">{shortcut}</KeyHint>}
          </TooltipPrimitive.Content>
        </TooltipPrimitive.Portal>
      </TooltipPrimitive.Root>
    </TooltipPrimitive.Provider>
  );
}

export { TooltipPrimitive };
