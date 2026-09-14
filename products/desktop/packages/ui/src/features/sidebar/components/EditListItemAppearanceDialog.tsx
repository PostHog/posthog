import { type DragDropEvents, DragDropProvider } from "@dnd-kit/react";
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
import {
  ANALYTICS_EVENTS,
  type TaskListAppearanceChangedProperties,
} from "@posthog/shared/analytics-events";
import { TaskStatusDot } from "@posthog/ui/features/sidebar/components/items/TaskStatusDot";
import { taskDot } from "@posthog/ui/features/sidebar/components/items/taskStatusVocabulary";
import { taskMetadata } from "@posthog/ui/features/sidebar/components/ListItemMetadata";
import { SidebarItem } from "@posthog/ui/features/sidebar/components/SidebarItem";
import {
  LIST_ITEM_METADATA_FIELDS,
  type ListItemMetadataField,
  moveListItemMetadataField,
} from "@posthog/ui/features/sidebar/listItemAppearance";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { track } from "@posthog/ui/shell/analytics";
import { useEffect, useRef, useState } from "react";
import { SortableListItemMetadataField } from "./SortableListItemMetadataField";

interface PreviewTask
  extends Pick<
    TaskData,
    "repository" | "branchName" | "linkedBranch" | "lastActivityAt"
  > {
  id: string;
  title: string;
  creatorName: string;
}

/** Ages that read as a list someone is actually working in. */
const PREVIEW_AGES_MS = [2 * 3_600_000, 3 * 86_400_000, 3 * 7 * 86_400_000];

/** The preview rows, dated against now rather than against module load. */
function datedPreview(): PreviewTask[] {
  return PREVIEW_TASKS.map((task, index) => ({
    ...task,
    lastActivityAt: Date.now() - PREVIEW_AGES_MS[index],
  }));
}

const PREVIEW_TASKS: Omit<PreviewTask, "lastActivityAt">[] = [
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
  surface,
  open,
  onOpenChange,
}: {
  /** Which list it was opened from. The setting itself is shared by both. */
  surface: TaskListAppearanceChangedProperties["surface"];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  // Dated when the dialog opens, so the preview's ages are the ages the list
  // is showing rather than whenever this module loaded.
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
  // The order when the drag began. dragover reorders in place, so a canceled
  // drag (Escape, pointercancel) would otherwise leave the half-dragged order
  // for Save to store; this puts it back.
  const orderBeforeDrag = useRef<ListItemMetadataField[] | null>(null);

  useEffect(() => {
    if (!open) return;
    setFieldOrder(orderedFieldList(storedFields));
    setSelectedFields(new Set(storedFields));
    lastMove.current = null;
  }, [open, storedFields]);

  const handleDragStart: DragDropEvents["dragstart"] = () => {
    lastMove.current = null;
    orderBeforeDrag.current = fieldOrder;
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

  const handleDragEnd: DragDropEvents["dragend"] = (event) => {
    const before = orderBeforeDrag.current;
    orderBeforeDrag.current = null;
    if (event.canceled && before) setFieldOrder(before);
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
  // Dated per render, so the ages are the ages the list is showing rather than
  // whenever this module loaded. Three objects from three constants.
  const previewTasks = datedPreview();

  const handleSave = () => {
    const changed =
      visibleFields.length !== storedFields.length ||
      visibleFields.some((field, index) => field !== storedFields[index]);
    if (changed) {
      setStoredFields(visibleFields);
      track(ANALYTICS_EVENTS.TASK_LIST_APPEARANCE_CHANGED, {
        secondary_fields: visibleFields,
        secondary_field_count: visibleFields.length,
        surface,
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
            Add context under each session name to find related work faster.
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
            {/* Not `disabled` rows: that dims them, and the preview has to
                carry the list's real colours to be worth looking at. Nothing
                inside answers a pointer instead. */}
            <div className="pointer-events-none h-[132px] rounded-(--radius-3) border border-border bg-(--gray-2) p-2">
              {previewTasks.map((task) => (
                <SidebarItem
                  key={task.id}
                  depth={0}
                  // The same leading mark a settled session carries in the
                  // list, so the preview reads as the list it stands for.
                  icon={<TaskStatusDot dot={taskDot({})} />}
                  label={task.title}
                  subtitle={taskMetadata(task, task.creatorName, visibleFields)}
                  tabIndex={-1}
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
              onDragEnd={handleDragEnd}
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
