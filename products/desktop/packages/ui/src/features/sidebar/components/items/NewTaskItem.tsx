import { Plus } from "@phosphor-icons/react";
import { Badge } from "@posthog/quill";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { isContentEmpty } from "@posthog/ui/features/message-editor/content";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { isTaskInputSessionId } from "@posthog/ui/features/task-detail/taskInputSession";
import type { MouseEventHandler } from "react";
import { SidebarItem } from "../SidebarItem";
import { SidebarKbdHint } from "./SidebarKbdHint";

interface NewTaskItemProps {
  isActive: boolean;
  onClick: MouseEventHandler<Element>;
}

export function NewTaskItem({ isActive, onClick }: NewTaskItemProps) {
  const hasDraft = useDraftStore((state) =>
    Object.entries(state.drafts).some(
      ([sessionId, draft]) =>
        isTaskInputSessionId(sessionId) && !isContentEmpty(draft),
    ),
  );
  return (
    <SidebarItem
      depth={0}
      icon={<Plus size={16} weight={isActive ? "bold" : "regular"} />}
      label="New task"
      isActive={isActive}
      onClick={onClick}
      endContent={
        hasDraft ? (
          <Badge variant="default" title="You have unsubmitted changes">
            Draft
          </Badge>
        ) : null
      }
      endHint={<SidebarKbdHint keys={SHORTCUTS.NEW_TASK} />}
    />
  );
}
