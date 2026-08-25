import { EnvelopeSimple } from "@phosphor-icons/react";
import { Badge } from "@posthog/quill";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import type { MouseEventHandler } from "react";
import { SidebarItem } from "../SidebarItem";
import { SidebarCountBadge } from "./SidebarCountBadge";
import { SidebarKbdHint } from "./SidebarKbdHint";

interface InboxItemProps {
  isActive: boolean;
  onClick: MouseEventHandler<Element>;
  reportCount?: number;
  depth?: number;
}

export function InboxItem({
  isActive,
  onClick,
  reportCount = 0,
  depth = 0,
}: InboxItemProps) {
  return (
    <Tooltip
      content={
        reportCount > 0
          ? `${reportCount} live report${reportCount === 1 ? "" : "s"}`
          : "No live reports"
      }
      side="right"
    >
      <div>
        <SidebarItem
          depth={depth}
          icon={
            <EnvelopeSimple size={16} weight={isActive ? "fill" : "regular"} />
          }
          label={
            <>
              Self-driving
              <SidebarCountBadge
                count={reportCount}
                title={`${reportCount} live report${reportCount === 1 ? "" : "s"}`}
              />
            </>
          }
          badge={<Badge variant="warning">Beta</Badge>}
          isActive={isActive}
          onClick={onClick}
          endHint={<SidebarKbdHint keys={SHORTCUTS.INBOX} />}
        />
      </div>
    </Tooltip>
  );
}
