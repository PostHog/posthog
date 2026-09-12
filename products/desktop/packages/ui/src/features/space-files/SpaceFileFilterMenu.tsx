import {
  DEFAULT_SPACE_FILE_LIST_GROUPING,
  DEFAULT_SPACE_FILE_LIST_SETTINGS,
  DEFAULT_SPACE_FILE_LIST_SORT,
  hasCustomizedSpaceFileList,
  type SpaceFileListSettings,
} from "@posthog/core/canvas/spaceFileList";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuSeparator,
} from "@posthog/quill";
import { CanvasFilterMultiSelectSubmenu } from "@posthog/ui/features/canvas/components/CanvasFilterMultiSelectSubmenu";
import {
  type CanvasFilterOption,
  type CanvasMultiSelectOption,
  summarizeSpaceSelection,
} from "@posthog/ui/features/canvas/components/canvasFilterSelection";
import {
  FilterClearItem,
  FilterMenuTrigger,
  FilterRadioSubMenu,
} from "@posthog/ui/primitives/FilterMenu";
import type { ReactElement } from "react";

const SORT_OPTIONS: readonly CanvasFilterOption<
  SpaceFileListSettings["sort"]
>[] = [
  { value: "recently_updated", label: "Recently updated" },
  { value: "name", label: "Name" },
];

const GROUPING_OPTIONS: readonly CanvasFilterOption<
  SpaceFileListSettings["grouping"]
>[] = [
  { value: "none", label: "None" },
  { value: "space", label: "Space" },
  { value: "date", label: "Date" },
];

export function SpaceFileFilterMenu({
  spaceOptions,
  settings,
  onChange,
}: {
  spaceOptions: readonly CanvasMultiSelectOption[];
  settings: SpaceFileListSettings;
  onChange: (settings: SpaceFileListSettings) => void;
}): ReactElement {
  const active = hasCustomizedSpaceFileList(settings);
  const updateSetting = <Key extends keyof SpaceFileListSettings>(
    key: Key,
    value: SpaceFileListSettings[Key],
  ): void => onChange({ ...settings, [key]: value });

  return (
    <DropdownMenu>
      <FilterMenuTrigger
        active={active}
        label="Filter files"
        dataAttr="space-file-list-filter"
        size="icon-xs"
      />
      <DropdownMenuContent
        align="end"
        side="bottom"
        sideOffset={6}
        className="w-64"
        aria-label="Filter files"
      >
        <FilterRadioSubMenu
          label="Group by"
          options={GROUPING_OPTIONS}
          value={settings.grouping}
          defaultValue={DEFAULT_SPACE_FILE_LIST_GROUPING}
          onChange={(grouping) => updateSetting("grouping", grouping)}
        />
        <FilterRadioSubMenu
          label="Sort by"
          options={SORT_OPTIONS}
          value={settings.sort}
          defaultValue={DEFAULT_SPACE_FILE_LIST_SORT}
          onChange={(sort) => updateSetting("sort", sort)}
        />
        <DropdownMenuSeparator />
        <CanvasFilterMultiSelectSubmenu
          label="Space"
          summary={summarizeSpaceSelection(spaceOptions, settings.spaceIds)}
          options={spaceOptions}
          values={settings.spaceIds}
          onChange={(spaceIds) => updateSetting("spaceIds", spaceIds)}
          searchPlaceholder="Search spaces…"
          emptyLabel="No spaces found."
        />
        <FilterClearItem
          active={active}
          dataAttr="clear-space-file-list-filters"
          onClear={() => onChange(DEFAULT_SPACE_FILE_LIST_SETTINGS)}
        />
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
