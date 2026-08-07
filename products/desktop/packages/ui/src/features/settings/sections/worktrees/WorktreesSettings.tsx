import {
  buildTaskMap,
  groupWorktrees,
  parseWorktreeLimit,
} from "@posthog/core/settings/worktreeGrouping";
import { deleteWorktree as runDeleteWorktree } from "@posthog/core/settings/worktreeMaintenanceService";
import { useHostTRPC, useHostTRPCClient } from "@posthog/host-router/react";
import { Flex, Switch, Text, TextField } from "@radix-ui/themes";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { useCallback, useMemo, useState } from "react";
import { toast } from "../../../../primitives/toast";
import { logger } from "../../../../shell/logger";
import { useFolders } from "../../../folders/useFolders";
import { useSuspensionSettings } from "../../../suspension/useSuspensionSettings";
import { useDeleteTask } from "../../../tasks/useTaskCrudMutations";
import { useTasks } from "../../../tasks/useTasks";
import { WORKSPACE_QUERY_KEY } from "../../../workspace/identifiers";
import { SettingRow } from "../../SettingRow";
import { useSettingsStore } from "../../settingsStore";
import { WorktreeGroupSection } from "./WorktreeGroupSection";

const log = logger.scope("worktrees-settings");

export function WorktreesSettings() {
  const queryClient = useQueryClient();
  const trpc = useHostTRPC();
  const hostClient = useHostTRPCClient();
  const { settings, updateSettings } = useSuspensionSettings();
  const showSidebarWorktrees = useSettingsStore(
    (state) => state.showSidebarWorktrees,
  );
  const setShowSidebarWorktrees = useSettingsStore(
    (state) => state.setShowSidebarWorktrees,
  );
  const { mutateAsync: deleteTask } = useDeleteTask();
  const [deletingWorktrees, setDeletingWorktrees] = useState<Set<string>>(
    new Set(),
  );

  const { folders } = useFolders();
  const { data: tasks } = useTasks();

  const worktreeQueries = useQueries({
    queries: folders.map((folder) => ({
      queryKey: trpc.workspace.listGitWorktrees.queryKey({
        mainRepoPath: folder.path,
      }),
      queryFn: () =>
        hostClient.workspace.listGitWorktrees.query({
          mainRepoPath: folder.path,
        }),
      staleTime: 30_000,
    })),
  });

  const worktreeGroups = useMemo(
    () =>
      groupWorktrees(
        folders,
        worktreeQueries.map((q) => q?.data),
      ),
    [folders, worktreeQueries],
  );

  const taskMap = useMemo(() => buildTaskMap(tasks), [tasks]);

  const handleDeleteWorktree = useCallback(
    async (
      worktreePath: string,
      allTaskIds: string[],
      existingTaskIds: string[],
      folderPath: string,
    ) => {
      setDeletingWorktrees((prev) => new Set(prev).add(worktreePath));

      try {
        await runDeleteWorktree(
          {
            confirmDeleteWorktree: (params) =>
              hostClient.contextMenu.confirmDeleteWorktree.mutate(params),
            deleteWorkspace: (params) =>
              hostClient.workspace.delete.mutate(params),
            deleteWorktree: (params) =>
              hostClient.workspace.deleteWorktree.mutate(params),
            deleteTask: (taskId) => deleteTask(taskId),
            invalidate: async (path) => {
              await Promise.all([
                queryClient.invalidateQueries({
                  queryKey: WORKSPACE_QUERY_KEY,
                }),
                queryClient.invalidateQueries(
                  trpc.workspace.listGitWorktrees.queryFilter({
                    mainRepoPath: path,
                  }),
                ),
              ]);
            },
          },
          { worktreePath, allTaskIds, existingTaskIds, folderPath },
        );
      } catch (error) {
        log.error("Failed to delete worktree:", error);
      } finally {
        setDeletingWorktrees((prev) => {
          const next = new Set(prev);
          next.delete(worktreePath);
          return next;
        });
      }
    },
    [hostClient, trpc, deleteTask, queryClient],
  );

  const commitNumericField = useCallback(
    (
      e:
        | React.FocusEvent<HTMLInputElement>
        | React.KeyboardEvent<HTMLInputElement>,
      field: "maxActiveWorktrees" | "autoSuspendAfterDays",
      fallback: number,
    ) => {
      const input = e.currentTarget;
      const val = parseWorktreeLimit(input.value);
      const labels: Record<string, string> = {
        maxActiveWorktrees: "Max active worktrees",
        autoSuspendAfterDays: "Auto-suspend days",
      };
      if (val !== null) {
        updateSettings({ [field]: val });
        toast.success(`${labels[field]} updated to ${val}`);
      } else {
        input.value = String(settings?.[field] ?? fallback);
      }
    },
    [settings, updateSettings],
  );

  const isLoading = worktreeQueries.some((q) => q.isLoading);

  return (
    <Flex direction="column" gap="5">
      <Flex direction="column">
        <SettingRow
          label="Show worktrees in sidebar"
          description="List worktrees that have no task under each repo in the sidebar, so you can start a task in one with a click"
        >
          <Switch
            checked={showSidebarWorktrees}
            onCheckedChange={setShowSidebarWorktrees}
            size="1"
          />
        </SettingRow>
        <SettingRow
          label="Automatically suspend stale worktrees"
          description="Suspend stale worktrees to save disk space. Suspended worktrees can be restored at any time. Only disable if you prefer to manage worktrees manually."
        >
          <Switch
            checked={settings.autoSuspendEnabled}
            onCheckedChange={(checked) =>
              updateSettings({ autoSuspendEnabled: checked })
            }
            size="1"
          />
        </SettingRow>
        <SettingRow
          label="Max active worktrees"
          description="When this limit is reached, the least recently active worktree will be automatically suspended"
        >
          <TextField.Root
            key={`max-${settings.maxActiveWorktrees}`}
            type="number"
            size="1"
            min={1}
            disabled={!settings.autoSuspendEnabled}
            defaultValue={settings.maxActiveWorktrees}
            onBlur={(e) => commitNumericField(e, "maxActiveWorktrees", 5)}
            onKeyDown={(e) => {
              if (e.key === "Enter")
                commitNumericField(e, "maxActiveWorktrees", 5);
            }}
            className="w-[64px]"
          />
        </SettingRow>
        <SettingRow
          label="Auto-suspend after inactivity"
          description="Suspend worktrees with no activity for this many days"
          noBorder
        >
          <TextField.Root
            key={`days-${settings.autoSuspendAfterDays}`}
            type="number"
            size="1"
            min={1}
            disabled={!settings.autoSuspendEnabled}
            defaultValue={settings.autoSuspendAfterDays}
            onBlur={(e) => commitNumericField(e, "autoSuspendAfterDays", 7)}
            onKeyDown={(e) => {
              if (e.key === "Enter")
                commitNumericField(e, "autoSuspendAfterDays", 7);
            }}
            className="w-[64px]"
          />
        </SettingRow>
      </Flex>

      {isLoading ? (
        <Text color="gray" className="text-sm">
          Loading worktrees...
        </Text>
      ) : worktreeGroups.length === 0 ? (
        <Text color="gray" className="text-[13px]">
          Tasks that are run in a worktree will show up here.
        </Text>
      ) : (
        worktreeGroups.map((group) => (
          <WorktreeGroupSection
            key={group.folderPath}
            group={group}
            taskMap={taskMap}
            deletingWorktrees={deletingWorktrees}
            onDelete={handleDeleteWorktree}
          />
        ))
      )}
    </Flex>
  );
}
