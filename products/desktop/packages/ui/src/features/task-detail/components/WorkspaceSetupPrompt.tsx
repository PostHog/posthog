import { Folder, Warning } from "@phosphor-icons/react";
import {
  WORKSPACE_SETUP_SAGA,
  type WorkspaceSetupSaga,
} from "@posthog/core/task-detail/workspaceSetupSaga";
import { WORKSPACE_SETUP_SERVICE } from "@posthog/core/workspace/identifiers";
import type { WorkspaceSetupService } from "@posthog/core/workspace/WorkspaceSetupService";
import { useService } from "@posthog/di/react";
import { getTaskRepository } from "@posthog/shared";
import type { Task } from "@posthog/shared/domain-types";
import { Box, Button, Code, Flex, Spinner, Text } from "@radix-ui/themes";
import { useCallback, useMemo, useState } from "react";
import { FolderPicker } from "../../folder-picker/FolderPicker";
import { useFolders } from "../../folders/useFolders";
import { toastError } from "../../notifications/errorDetails";
import { useEnsureWorkspace } from "../../workspace/useWorkspaceMutations";

interface WorkspaceSetupPromptProps {
  taskId: string;
  task: Task;
}

export function WorkspaceSetupPrompt({
  taskId,
  task,
}: WorkspaceSetupPromptProps) {
  const [isSettingUp, setIsSettingUp] = useState(false);
  const [selectedPath, setSelectedPath] = useState("");
  const [pendingPath, setPendingPath] = useState<string | null>(null);
  const [detectedRepo, setDetectedRepo] = useState<string | null>(null);
  const repository = getTaskRepository(task);
  const { ensureWorkspace } = useEnsureWorkspace();
  const { addFolder } = useFolders();
  const setupService = useService<WorkspaceSetupService>(
    WORKSPACE_SETUP_SERVICE,
  );
  const setupSaga = useService<WorkspaceSetupSaga>(WORKSPACE_SETUP_SAGA);

  const executor = useMemo(
    () => ({ addFolder, ensureWorkspace }),
    [addFolder, ensureWorkspace],
  );

  const proceedWithSetup = useCallback(
    async (path: string) => {
      setPendingPath(null);
      setDetectedRepo(null);
      setSelectedPath(path);
      setIsSettingUp(true);

      const result = await setupSaga.setupWorkspace(executor, taskId, path);
      if (!result.success) {
        toastError("Failed to set up workspace", result.error);
      }

      setSelectedPath("");
      setIsSettingUp(false);
    },
    [taskId, executor, setupSaga],
  );

  const handleFolderSelect = useCallback(
    async (path: string) => {
      const evaluation = await setupService.evaluateFolderSelection(
        repository,
        path,
      );
      if (evaluation.kind === "mismatch") {
        setPendingPath(path);
        setDetectedRepo(evaluation.detectedRepo);
        return;
      }

      await proceedWithSetup(path);
    },
    [repository, proceedWithSetup, setupService],
  );

  const handleConfirm = useCallback(async () => {
    if (pendingPath) {
      await proceedWithSetup(pendingPath);
    }
  }, [pendingPath, proceedWithSetup]);

  const handleBack = useCallback(() => {
    setPendingPath(null);
    setDetectedRepo(null);
  }, []);

  return (
    <Flex
      align="center"
      justify="center"
      direction="column"
      gap="3"
      className="absolute inset-0"
    >
      {isSettingUp ? (
        <>
          <Spinner size="3" />
          <Text className="text-gray-11 text-sm">Setting up workspace...</Text>
        </>
      ) : pendingPath ? (
        <>
          <Warning size={32} weight="duotone" className="text-amber-9" />
          <Text className="font-medium text-base text-gray-12">
            Repository mismatch
          </Text>
          <Text align="center" className="max-w-xs text-gray-11 text-sm">
            This task is linked to <Code>{repository}</Code> but the selected
            folder belongs to <Code>{detectedRepo}</Code>.
          </Text>
          <Flex gap="2" mt="1">
            <Button variant="soft" color="gray" onClick={handleBack}>
              Go back
            </Button>
            <Button variant="solid" onClick={handleConfirm}>
              Continue anyway
            </Button>
          </Flex>
        </>
      ) : (
        <>
          <Folder size={32} weight="duotone" className="text-gray-9" />
          <Text className="font-medium text-base text-gray-12">
            Select a repository folder
          </Text>
          {repository && (
            <Text className="text-gray-11 text-sm">
              This task is linked to <Code>{repository}</Code>
            </Text>
          )}
          <Box mt="1">
            <FolderPicker
              value={selectedPath}
              onChange={handleFolderSelect}
              placeholder="Select folder..."
            />
          </Box>
        </>
      )}
    </Flex>
  );
}
