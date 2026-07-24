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
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
  MenuLabel,
} from "@posthog/quill";
import type { WorkspaceMode } from "@posthog/shared";
import { useMeQuery } from "@posthog/ui/features/auth/useMeQuery";
import { useFolders } from "@posthog/ui/features/folders/useFolders";
import { useSidebarStore } from "@posthog/ui/features/sidebar/sidebarStore";
import { useHoldSidebarPeek } from "@posthog/ui/features/sidebar/useHoldSidebarPeek";
import { Tooltip } from "@posthog/ui/primitives/Tooltip";
import { toast } from "@posthog/ui/primitives/toast";
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

  const handleOpenChange = useHoldSidebarPeek();

  return (
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
        <MenuLabel>Organize</MenuLabel>
        <DropdownMenuRadioGroup
          value={organizeMode}
          onValueChange={(value) =>
            setOrganizeMode(value as typeof organizeMode)
          }
        >
          <DropdownMenuRadioItem value="by-project">
            By project
          </DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="chronological">
            Chronological list
          </DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>

        <DropdownMenuSeparator />

        <MenuLabel>Sort by</MenuLabel>
        <DropdownMenuRadioGroup
          value={sortMode}
          onValueChange={(value) => setSortMode(value as typeof sortMode)}
        >
          <DropdownMenuRadioItem value="created">Created</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="updated">Updated</DropdownMenuRadioItem>
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
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function TasksHeader() {
  return (
    <div className="shrink-0 px-2">
      <MenuLabel className="flex items-center justify-between pt-0 pr-0 pb-0.5">
        Tasks
        <span className="flex items-center">
          <AddFolderButton />
          <TaskSearchButton />
          <TaskFilterMenu />
        </span>
      </MenuLabel>
    </div>
  );
}
