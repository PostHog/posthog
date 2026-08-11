import { Plus } from "@phosphor-icons/react";
import { Badge } from "@posthog/quill";
import { SHORTCUTS } from "@posthog/ui/features/command/keyboard-shortcuts";
import { isContentEmpty } from "@posthog/ui/features/message-editor/content";
import { useDraftStore } from "@posthog/ui/features/message-editor/draftStore";
import { SidebarItem } from "../SidebarItem";
import { SidebarKbdHint } from "./SidebarKbdHint";

interface NewTaskItemProps {
  isActive: boolean;
  onClick: () => void;
}

export function NewTaskItem({ isActive, onClick }: NewTaskItemProps) {
  const hasDraft = useDraftStore(
    (s) => !isContentEmpty(s.drafts["task-input"]),
  );
  return (
    <SidebarItem
      depth={0}
      icon={<Plus size={16} weight={isActive ? "bold" : "regular"} />}
      label="New task"
      isActive={isActive}
      onClick={onClick}
      endContent={
        <>
          {hasDraft ? (
            <Badge variant="default" title="You have unsubmitted changes">
              Draft
            </Badge>
          ) : null}
          <SidebarKbdHint keys={SHORTCUTS.NEW_TASK} />
        </>
      }
    />
  );
}
