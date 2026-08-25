import { EnvelopeSimple } from "@phosphor-icons/react";
import { Badge } from "@posthog/quill";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import type { MouseEventHandler } from "react";
import { SidebarItem } from "../SidebarItem";
import { SidebarKbdHint } from "./SidebarKbdHint";
import { SidebarNotificationDot } from "./SidebarNotificationDot";

interface InboxItemProps {
  isActive: boolean;
  onClick: MouseEventHandler<Element>;
  decisionCount?: number;
  depth?: number;
}

export function InboxItem({
  isActive,
  onClick,
  decisionCount = 0,
  depth = 0,
}: InboxItemProps) {
  return (
    <Tooltip
      content={
        decisionCount > 0
          ? `${decisionCount} report${decisionCount === 1 ? " needs" : "s need"} a decision`
          : "No reports need a decision"
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
              <SidebarNotificationDot
                show={decisionCount > 0}
                title={`${decisionCount} report${decisionCount === 1 ? " needs" : "s need"} a decision`}
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
