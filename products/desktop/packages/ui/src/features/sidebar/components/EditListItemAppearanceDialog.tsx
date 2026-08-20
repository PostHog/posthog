import { type DragDropEvents, DragDropProvider } from "@dnd-kit/react";
import { GitBranch } from "@phosphor-icons/react";
import type { TaskData } from "@posthog/core/sidebar/sidebarData.types";
import {
  Button,
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Text,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import {
  formatListItemMetadata,
  LIST_ITEM_METADATA_FIELDS,
  type ListItemMetadataField,
  moveListItemMetadataField,
} from "@posthog/ui/features/sidebar/listItemAppearance";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef, useState } from "react";
import { SortableListItemMetadataField } from "./SortableListItemMetadataField";

interface PreviewTask
  extends Pick<TaskData, "repository" | "branchName" | "linkedBranch"> {
  id: string;
  title: string;
  creatorName: string;
}

const PREVIEW_TASKS: PreviewTask[] = [
  {
    id: "preview-review",
    title: "Address feedback on session list",
    repository: {
      fullPath: "posthog/code",
      name: "code",
      organization: "posthog",
    },
    branchName: "posthog/session-list",
    linkedBranch: "posthog/session-list",
    creatorName: "Ada Lovelace",
  },
  {
    id: "preview-replay",
    title: "Fix recording loading state",
    repository: {
      fullPath: "posthog/posthog",
      name: "posthog",
      organization: "posthog",
    },
    branchName: "fix/replay-loading",
    linkedBranch: "fix/replay-loading",
    creatorName: "Grace Hopper",
  },
  {
    id: "preview-docs",
    title: "Update SDK installation docs",
    repository: {
      fullPath: "posthog/posthog-js",
      name: "posthog-js",
      organization: "posthog",
    },
    branchName: "docs/sdk-installation",
    linkedBranch: null,
    creatorName: "Katherine Johnson",
  },
];

function orderedFieldList(
  selectedFields: readonly ListItemMetadataField[],
): ListItemMetadataField[] {
  const selected = new Set(selectedFields);
  return [
    ...selectedFields,
    ...LIST_ITEM_METADATA_FIELDS.filter((field) => !selected.has(field)),
  ];
}

export function EditListItemAppearanceDialog({
  open,
  onOpenChange,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const storedFields = useSidebarStore((state) => state.listItemMetadataFields);
  const setStoredFields = useSidebarStore(
    (state) => state.setListItemMetadataFields,
  );
  const [fieldOrder, setFieldOrder] = useState<ListItemMetadataField[]>(() =>
    orderedFieldList(storedFields),
  );
  const [selectedFields, setSelectedFields] = useState<
    Set<ListItemMetadataField>
  >(() => new Set(storedFields));
  const lastMove = useRef<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setFieldOrder(orderedFieldList(storedFields));
    setSelectedFields(new Set(storedFields));
    lastMove.current = null;
  }, [open, storedFields]);

  const handleDragStart: DragDropEvents["dragstart"] = () => {
    lastMove.current = null;
  };

  const handleDragOver: DragDropEvents["dragover"] = (event) => {
    const sourceId = event.operation.source?.id;
    const targetId = event.operation.target?.id;
    if (!sourceId || !targetId || sourceId === targetId) return;
    const moveKey = `${String(sourceId)}->${String(targetId)}`;
    if (lastMove.current === moveKey) return;
    lastMove.current = moveKey;
    setFieldOrder((current) =>
      moveListItemMetadataField(current, String(sourceId), String(targetId)),
    );
  };

  const toggleField = (field: ListItemMetadataField, checked: boolean) => {
    setSelectedFields((current) => {
      const next = new Set(current);
      if (checked) next.add(field);
      else next.delete(field);
      return next;
    });
  };

  const visibleFields = fieldOrder.filter((field) => selectedFields.has(field));

  const handleSave = () => {
    const changed =
      visibleFields.length !== storedFields.length ||
      visibleFields.some((field, index) => field !== storedFields[index]);
    if (changed) {
      setStoredFields(visibleFields);
      track(ANALYTICS_EVENTS.TASK_LIST_APPEARANCE_CHANGED, {
        secondary_fields: visibleFields,
        secondary_field_count: visibleFields.length,
      });
    }
    onOpenChange(false);
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent showCloseButton={false} className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit list item appearance</DialogTitle>
          <DialogDescription>
            Add context under each task name to find related work faster.
          </DialogDescription>
        </DialogHeader>

        <DialogBody viewportClassName="flex flex-col gap-5">
          <section aria-labelledby="list-item-preview-heading">
            <Text
              id="list-item-preview-heading"
              size="sm"
              weight="medium"
              className="mb-2 block"
            >
              Preview
            </Text>
            <div className="rounded-(--radius-3) border border-border bg-(--gray-2) p-2">
              {PREVIEW_TASKS.map((task) => (
                <SidebarItem
                  key={task.id}
                  depth={0}
                  icon={<GitBranch size={14} />}
                  label={task.title}
                  subtitle={formatListItemMetadata(
                    task,
                    task.creatorName,
                    visibleFields,
                  )}
                  disabled
                />
              ))}
            </div>
          </section>

          <section aria-labelledby="second-row-heading">
            <Text id="second-row-heading" size="sm" weight="medium">
              Second row
            </Text>
            <Text size="xs" variant="muted" className="mt-0.5 mb-3 block">
              Choose the details to show. Drag them into the order you want.
              Leave all unchecked for a single-row list.
            </Text>
            <DragDropProvider
              onDragStart={handleDragStart}
              onDragOver={handleDragOver}
            >
              <div className="flex flex-col gap-2">
                {fieldOrder.map((field, index) => (
                  <SortableListItemMetadataField
                    key={field}
                    field={field}
                    index={index}
                    checked={selectedFields.has(field)}
                    onCheckedChange={(checked) => toggleField(field, checked)}
                  />
                ))}
              </div>
            </DragDropProvider>
          </section>
        </DialogBody>

        <DialogFooter>
          <DialogClose
            render={
              <Button
                variant="outline"
                data-attr="list-item-appearance-cancel"
              />
            }
          >
            Cancel
          </DialogClose>
          <Button
            variant="primary"
            data-attr="list-item-appearance-save"
            onClick={handleSave}
          >
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
