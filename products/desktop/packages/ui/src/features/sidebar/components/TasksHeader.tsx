import {
  Cloud,
  Desktop,
  FolderPlus,
  FunnelSimple as FunnelSimpleIcon,
  GitBranch,
  type Icon,
  MagnifyingGlass,
} from "@phosphor-icons/react";
import { ALL_WORKSPACE_MODES } from "@posthog/core/sidebar/buildSidebarData";
import { useHostTRPCClient } from "@posthog/host-router/react";
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  MenuLabel,
} from "@posthog/quill";
import { PROJECT_BLUEBIRD_FLAG, type WorkspaceMode } from "@posthog/shared";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { useFeatureFlag } from "@posthog/ui/features/feature-flags/useFeatureFlag";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { EditListItemAppearanceDialog } from "@posthog/ui/features/sidebar/components/EditListItemAppearanceDialog";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useHoldSidebarPeek } from "@posthog/ui/features/sidebar/useHoldSidebarPeek";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { toast } from "@posthog/ui/primitives/toast";
import { track } from "@posthog/ui/shell/analytics";
import { useCommandMenuStore } from "@posthog/ui/shell/commandMenuStore";
import { logger } from "@posthog/ui/shell/logger";
import { useState } from "react";

const log = logger.scope("tasks-header");

// Record (not a hand-maintained array) so adding a WorkspaceMode forces a
// compile error here instead of silently missing a checkbox.
const ENVIRONMENT_META: Record<WorkspaceMode, { label: string; icon: Icon }> = {
  worktree: { label: "Worktree", icon: GitBranch },
  local: { label: "Local", icon: Desktop },
  cloud: { label: "Cloud", icon: Cloud },
};

function AddFolderButton() {
  const trpcClient = useHostTRPCClient();
  const { addFolder } = useFolders();
  const [isOpening, setIsOpening] = useState(false);

  const handleClick = async () => {
    if (isOpening) return;
    setIsOpening(true);
    try {
      const selectedPath = await trpcClient.os.selectDirectory.query();
      if (selectedPath) await addFolder(selectedPath);
    } catch (error) {
      log.error("Failed to add folder", error);
      toast.error("Couldn't add folder");
    } finally {
      setIsOpening(false);
    }
  };

  return (
    <Tooltip content="Add folder" side="bottom">
      <Button
        type="button"
        aria-label="Add folder"
        size="icon-sm"
        onClick={handleClick}
        disabled={isOpening}
      >
        <FolderPlus size={14} />
      </Button>
    </Tooltip>
  );
}

function TaskSearchButton() {
  const openCommandMenu = useCommandMenuStore((state) => state.open);
  return (
    <Button
      type="button"
      aria-label="Search tasks"
      size="icon-sm"
      onClick={() => openCommandMenu()}
    >
      <MagnifyingGlass size={14} />
    </Button>
  );
}

function TaskFilterMenu() {
  const organizeMode = useSidebarStore((state) => state.organizeMode);
  const sortMode = useSidebarStore((state) => state.sortMode);
  const showAllUsers = useSidebarStore((state) => state.showAllUsers);
  const showInternal = useSidebarStore((state) => state.showInternal);
  const setOrganizeMode = useSidebarStore((state) => state.setOrganizeMode);
  const setSortMode = useSidebarStore((state) => state.setSortMode);
  const setShowAllUsers = useSidebarStore((state) => state.setShowAllUsers);
  const setShowInternal = useSidebarStore((state) => state.setShowInternal);
  const taskTypeFilter = useSidebarStore((state) => state.taskTypeFilter);
  const toggleTaskType = useSidebarStore((state) => state.toggleTaskType);
  const { data: currentUser } = useMeQuery();
  const isStaff = currentUser?.is_staff === true;
  const [appearanceDialogOpen, setAppearanceDialogOpen] = useState(false);

  const handleOpenChange = useHoldSidebarPeek();
  const handleOrganizeModeChange = (value: string) => {
    const nextMode = value as typeof organizeMode;
    if (nextMode === organizeMode) return;
    setOrganizeMode(nextMode);
    track(ANALYTICS_EVENTS.TASK_LIST_GROUPING_CHANGED, {
      group_by: nextMode === "by-project" ? "repository" : "date",
      sort_by: sortMode,
      surface: "sidebar",
    });
  };

  return (
    <>
      <DropdownMenu onOpenChange={handleOpenChange}>
        <DropdownMenuTrigger
          render={
            <Button type="button" aria-label="Filter tasks" size="icon-sm">
              <FunnelSimpleIcon size={14} />
            </Button>
          }
        />
        <DropdownMenuContent
          align="start"
          side="bottom"
          sideOffset={6}
          className="min-w-fit"
        >
          <MenuLabel>Group by</MenuLabel>
          <DropdownMenuRadioGroup
            value={organizeMode}
            onValueChange={handleOrganizeModeChange}
          >
            <DropdownMenuRadioItem value="by-project">
              Repository
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="chronological">
              Date
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>

          <DropdownMenuSeparator />

          <MenuLabel>Sort by</MenuLabel>
          <DropdownMenuRadioGroup
            value={sortMode}
            onValueChange={(value) => setSortMode(value as typeof sortMode)}
          >
            <DropdownMenuRadioItem value="created">
              Created
            </DropdownMenuRadioItem>
            <DropdownMenuRadioItem value="updated">
              Updated
            </DropdownMenuRadioItem>
          </DropdownMenuRadioGroup>

          {import.meta.env.DEV && (
            <>
              <DropdownMenuSeparator />

              <MenuLabel>Show</MenuLabel>
              <DropdownMenuRadioGroup
                value={showAllUsers ? "all" : "mine"}
                onValueChange={(value) => setShowAllUsers(value === "all")}
              >
                <DropdownMenuRadioItem value="mine">
                  My tasks
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="all">
                  All tasks
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </>
          )}

          {isStaff && (
            <>
              <DropdownMenuSeparator />

              <MenuLabel>Task visibility</MenuLabel>
              <DropdownMenuRadioGroup
                value={showInternal ? "internal" : "external"}
                onValueChange={(value) => setShowInternal(value === "internal")}
              >
                <DropdownMenuRadioItem value="external">
                  External
                </DropdownMenuRadioItem>
                <DropdownMenuRadioItem value="internal">
                  Internal
                </DropdownMenuRadioItem>
              </DropdownMenuRadioGroup>
            </>
          )}

          <DropdownMenuSeparator />

          <DropdownMenuSub>
            <DropdownMenuSubTrigger>Environment</DropdownMenuSubTrigger>
            <DropdownMenuSubContent side="right" sideOffset={4}>
              {ALL_WORKSPACE_MODES.map((mode) => {
                const { label, icon: Icon } = ENVIRONMENT_META[mode];
                return (
                  <DropdownMenuCheckboxItem
                    key={mode}
                    checked={taskTypeFilter.includes(mode)}
                    closeOnClick={false}
                    onCheckedChange={() => toggleTaskType(mode)}
                  >
                    <Icon size={14} />
                    {label}
                  </DropdownMenuCheckboxItem>
                );
              })}
            </DropdownMenuSubContent>
          </DropdownMenuSub>

          <DropdownMenuSeparator />

          <DropdownMenuItem
            data-attr="edit-list-item-appearance"
            onClick={() => setAppearanceDialogOpen(true)}
          >
            Edit list item appearance…
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <EditListItemAppearanceDialog
        surface="sidebar"
        open={appearanceDialogOpen}
        onOpenChange={setAppearanceDialogOpen}
      />
    </>
  );
}

export function TasksHeader() {
  const bluebirdEnabled = useFeatureFlag(
    PROJECT_BLUEBIRD_FLAG,
    import.meta.env.DEV,
  );
  const channelsEnabled =
    useSidebarStore((state) => state.channelsEnabled) && bluebirdEnabled;
  const setChannelsEnabled = useSidebarStore(
    (state) => state.setChannelsEnabled,
  );

  const handleModeChange = (showChannels: boolean) => {
    if (showChannels === channelsEnabled) return;
    setChannelsEnabled(showChannels);
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: "toggle_channels",
      surface: "nav",
    });
    track(ANALYTICS_EVENTS.CHANNEL_ACTION, {
      action_type: showChannels ? "enter_space" : "leave_space",
      surface: "nav",
    });
  };

  return (
    <div className="shrink-0 px-2">
      <div className="flex min-h-7 items-center justify-between pb-0.5">
        {bluebirdEnabled ? (
          <fieldset
            className="m-0 flex min-w-0 items-center gap-px rounded border-0 bg-fill-secondary p-px"
            aria-label="Sidebar content"
          >
            <Button
              type="button"
              size="xs"
              className="px-1.5 font-normal text-gray-10 text-xs normal-case hover:text-gray-12 data-[active]:bg-accent-4 data-[active]:font-medium data-[active]:text-gray-12 data-[active]:shadow-sm"
              aria-pressed={channelsEnabled}
              data-active={channelsEnabled || undefined}
              onClick={() => handleModeChange(true)}
            >
              Channels
            </Button>
            <Button
              type="button"
              size="xs"
              className="px-1.5 font-normal text-gray-10 text-xs normal-case hover:text-gray-12 data-[active]:bg-accent-4 data-[active]:font-medium data-[active]:text-gray-12 data-[active]:shadow-sm"
              aria-pressed={!channelsEnabled}
              data-active={!channelsEnabled || undefined}
              onClick={() => handleModeChange(false)}
            >
              List
            </Button>
          </fieldset>
        ) : (
          <span className="font-medium text-xs">List</span>
        )}
        {!channelsEnabled && (
          <span className="flex items-center">
            <AddFolderButton />
            <TaskSearchButton />
            <TaskFilterMenu />
          </span>
        )}
      </div>
    </div>
  );
}
