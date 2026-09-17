import { useSortable } from "@dnd-kit/react/sortable";
import {
  Clock,
  DotsSixVertical,
  GitBranch,
  GitFork,
  User,
} from "@phosphor-icons/react";
import { Checkbox, cn, Label } from "@posthog/quill";
import {
  LIST_ITEM_METADATA_LABELS,
  type ListItemMetadataField,
} from "@posthog/ui/features/sidebar/listItemAppearance";
import type { ComponentType, RefCallback } from "react";

const FIELD_ICONS: Record<
  ListItemMetadataField,
  ComponentType<{ size?: number | string }>
> = {
  repository: GitFork,
  branch: GitBranch,
  creator: User,
  activity: Clock,
};

export function SortableListItemMetadataField({
  field,
  index,
  checked,
  onCheckedChange,
}: {
  field: ListItemMetadataField;
  index: number;
  checked: boolean;
  onCheckedChange: (checked: boolean) => void;
}) {
  const { ref, handleRef, isDragging } = useSortable({
    id: field,
    index,
    group: "list-item-metadata",
    transition: { duration: 200, easing: "ease" },
  });
  const Icon = FIELD_ICONS[field];
  const checkboxId = `list-item-metadata-${field}`;

  return (
    <div
      ref={ref}
      className={cn(
        "rounded-(--radius-2) border border-border bg-(--gray-1) px-2.5 py-2",
        isDragging && "opacity-50",
      )}
    >
      <div className="flex items-center gap-2">
        <button
          ref={handleRef as RefCallback<HTMLButtonElement>}
          type="button"
          title={`Drag ${LIST_ITEM_METADATA_LABELS[field]} to reorder`}
          aria-label={`Drag ${LIST_ITEM_METADATA_LABELS[field]} to reorder`}
          data-attr={`list-item-metadata-drag-${field}`}
          className="shrink-0 cursor-grab text-gray-9 hover:text-gray-11"
        >
          <DotsSixVertical size={14} />
        </button>
        <Label
          htmlFor={checkboxId}
          className="flex flex-1 cursor-pointer items-center gap-2"
        >
          <Checkbox
            id={checkboxId}
            checked={checked}
            data-attr={`list-item-metadata-${field}`}
            onCheckedChange={(value) => onCheckedChange(value === true)}
          />
          <Icon size={15} />
          {LIST_ITEM_METADATA_LABELS[field]}
        </Label>
      </div>
    </div>
  );
}
