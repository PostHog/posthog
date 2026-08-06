import {
  ArrowCounterClockwiseIcon,
  CheckSquare,
  CodeIcon,
  CopyIcon,
  FilePlus,
  MinusIcon,
  PlusIcon,
} from "@phosphor-icons/react";
import { getFileExtension } from "@posthog/shared";
import {
  ANALYTICS_EVENTS,
  type FileChangeType,
} from "@posthog/shared/analytics-events";
import type { ChangedFile, Task } from "@posthog/shared/domain-types";
import {
  Badge,
  Box,
  Button,
  DropdownMenu,
  Flex,
  IconButton,
  Spinner,
  Text,
} from "@radix-ui/themes";
import { Fragment, useCallback, useMemo, useState } from "react";
import { PanelMessage } from "../../../primitives/PanelMessage";
import { Tooltip } from "../../../primitives/Tooltip";
import { TreeFileRow } from "../../../primitives/TreeDirectoryRow";
import { track } from "../../../shell/analytics";
import { useEffectiveDiffSource } from "../../code-review/hooks/useEffectiveDiffSource";
import { useReviewNavigationStore } from "../../code-review/reviewNavigationStore";
import { isFileViewed } from "../../code-review/reviewShellParts";
import { useReviewViewedContext } from "../../code-review/reviewViewedContext";
import { useExternalAppAction } from "../../external-apps/useExternalAppAction";
import { useExternalApps } from "../../external-apps/useExternalApps";
import {
  useGitQueries,
  useLocalBranchChangedFiles,
  usePrChangedFiles,
} from "../../git-interaction/useGitQueries";
import { makeFileKey } from "../../git-interaction/utils/fileKey";
import { getStatusIndicator } from "../../git-interaction/utils/gitStatusUtils";
import { partitionByStaged } from "../../git-interaction/utils/partitionByStaged";
import { useFileContextMenu } from "../../sessions/components/useFileContextMenu";
import { useCwd } from "../../sidebar/useCwd";
import { useIsCloudTask } from "../../workspace/useIsCloudTask";
import { useWorkspace } from "../../workspace/useWorkspace";
import { useCloudChangedFiles } from "../hooks/useCloudChangedFiles";
import { useDiscardFile } from "../hooks/useDiscardFile";
import { useStageToggle } from "../hooks/useStageToggle";
import { ChangesTreeView } from "./ChangesTreeView";

interface ChangesPanelProps {
  taskId: string;
  task: Task;
}

interface ChangedFileItemProps {
  file: ChangedFile;
  taskId: string;
  fileKey: string;
  isActive: boolean;
  repoPath?: string;
  mainRepoPath?: string;
  onStageToggle?: (file: ChangedFile) => void;
  onDiscard?: (file: ChangedFile, fileName: string) => void;
  depth?: number;
}

function CompactIconButton({
  tooltip,
  onClick,
  children,
}: {
  tooltip: string;
  onClick: (e: React.MouseEvent) => void;
  children: React.ReactNode;
}) {
  return (
    <Tooltip content={tooltip}>
      <IconButton
        size="1"
        variant="ghost"
        color="gray"
        onClick={onClick}
        className="mx-0.5 size-[18px] shrink-0 p-0"
      >
        {children}
      </IconButton>
    </Tooltip>
  );
}

function ChangedFileItem({
  file,
  taskId,
  fileKey,
  isActive,
  repoPath,
  mainRepoPath,
  onStageToggle,
  onDiscard,
  depth = 0,
}: ChangedFileItemProps) {
  const requestScrollToFile = useReviewNavigationStore(
    (state) => state.requestScrollToFile,
  );
  const openExternalApp = useExternalAppAction();
  const { detectedApps } = useExternalApps();
  const workspace = useWorkspace(taskId);
  const { openForFile } = useFileContextMenu();
  const viewedContext = useReviewViewedContext();

  const [isHovered, setIsHovered] = useState(false);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);

  const isLocal = !!repoPath;
  const isToolbarVisible = isLocal && (isHovered || isDropdownOpen);

  const fileName = file.path.split("/").pop() || file.path;
  const fullPath = repoPath ? `${repoPath}/${file.path}` : file.path;
  const indicator = getStatusIndicator(file.status);
  const currentSignature = viewedContext?.currentSignatures.get(fileKey);
  const viewed =
    currentSignature !== undefined &&
    isFileViewed(viewedContext?.viewedRecord[fileKey], currentSignature);

  const handleClick = () => {
    track(ANALYTICS_EVENTS.FILE_DIFF_VIEWED, {
      change_type: file.status as FileChangeType,
      file_extension: getFileExtension(file.path),
      task_id: taskId,
    });
    requestScrollToFile(taskId, fileKey);
  };

  const workspaceContext = {
    workspace,
    mainRepoPath,
  };

  const handleContextMenu = repoPath
    ? async (e: React.MouseEvent) => {
        e.preventDefault();
        await openForFile({
          absolutePath: fullPath,
          filename: fileName,
          workspace,
          mainRepoPath,
        });
      }
    : undefined;

  const handleOpenWith = async (appId: string) => {
    await openExternalApp(
      { type: "open-in-app", appId },
      fullPath,
      fileName,
      workspaceContext,
    );

    if (document.activeElement instanceof HTMLElement) {
      document.activeElement.blur();
    }
  };

  const handleCopyPath = async () => {
    await openExternalApp({ type: "copy-path" }, fullPath, fileName);
  };

  const handleDiscard = onDiscard
    ? (e: React.MouseEvent) => {
        e.preventDefault();
        e.stopPropagation();
        onDiscard(file, fileName);
      }
    : undefined;

  const hasLineStats =
    file.linesAdded !== undefined || file.linesRemoved !== undefined;

  const tooltipContent = `${file.path} - ${indicator.fullLabel}`;

  const trailing = (
    <>
      {hasLineStats && !isToolbarVisible && (
        <Flex
          align="center"
          gap="1"
          className="shrink-0 font-mono text-[10px] leading-none"
        >
          {(file.linesAdded ?? 0) > 0 && (
            <Text className="text-(--green-9)">+{file.linesAdded}</Text>
          )}
          {(file.linesRemoved ?? 0) > 0 && (
            <Text className="text-(--red-9)">-{file.linesRemoved}</Text>
          )}
        </Flex>
      )}

      {isToolbarVisible && (handleDiscard || onStageToggle) && (
        <Flex align="center" gap="1" className="shrink-0">
          {onStageToggle && (
            <CompactIconButton
              tooltip={file.staged ? "Unstage" : "Stage"}
              onClick={(e) => {
                e.preventDefault();
                e.stopPropagation();
                onStageToggle(file);
              }}
            >
              {file.staged ? <MinusIcon size={12} /> : <PlusIcon size={12} />}
            </CompactIconButton>
          )}
          {handleDiscard && (
            <CompactIconButton
              tooltip="Discard changes"
              onClick={handleDiscard}
            >
              <ArrowCounterClockwiseIcon size={12} />
            </CompactIconButton>
          )}

          <DropdownMenu.Root
            open={isDropdownOpen}
            onOpenChange={setIsDropdownOpen}
          >
            <Tooltip content="Open file">
              <DropdownMenu.Trigger>
                <IconButton
                  size="1"
                  variant="ghost"
                  color="gray"
                  onClick={(e) => e.stopPropagation()}
                  className="h-[18px] w-[18px] shrink-0 p-0"
                >
                  <FilePlus size={12} weight="regular" />
                </IconButton>
              </DropdownMenu.Trigger>
            </Tooltip>
            <DropdownMenu.Content size="1" align="end">
              {detectedApps
                .filter(
                  (app) => app.type !== "terminal" && app.type !== "git-client",
                )
                .map((app) => (
                  <DropdownMenu.Item
                    key={app.id}
                    onSelect={() => handleOpenWith(app.id)}
                  >
                    <Flex align="center" gap="2">
                      {app.icon ? (
                        <img
                          src={app.icon}
                          width={16}
                          height={16}
                          alt=""
                          className="rounded-[2px]"
                        />
                      ) : (
                        <CodeIcon size={16} weight="regular" />
                      )}
                      <Text className="text-[13px]">{app.name}</Text>
                    </Flex>
                  </DropdownMenu.Item>
                ))}
              <DropdownMenu.Separator />
              <DropdownMenu.Item onSelect={handleCopyPath}>
                <Flex align="center" gap="2">
                  <CopyIcon size={16} weight="regular" />
                  <Text className="text-[13px]">Copy Path</Text>
                </Flex>
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Root>
        </Flex>
      )}

      <Badge
        size="1"
        color={indicator.color}
        className="shrink-0 px-[4px] py-0 text-[10px]"
      >
        {indicator.label}
      </Badge>
      {viewed && (
        <CheckSquare
          aria-label="Viewed"
          size={13}
          weight="fill"
          className="shrink-0 text-(--accent-9)"
        />
      )}
    </>
  );

  return (
    <Tooltip content={tooltipContent} side="top" delayDuration={500}>
      <TreeFileRow
        fileName={fileName}
        depth={depth}
        isActive={isActive}
        onClick={handleClick}
        onDoubleClick={handleClick}
        onContextMenu={handleContextMenu}
        onMouseEnter={() => setIsHovered(true)}
        onMouseLeave={() => setIsHovered(false)}
        trailing={trailing}
      />
    </Tooltip>
  );
}

function CloudChangesPanel({ taskId, task }: ChangesPanelProps) {
  const {
    prUrl,
    effectiveBranch,
    isRunActive,
    changedFiles,
    isLoading,
    hasError,
  } = useCloudChangedFiles(taskId, task);

  const activeFilePath = useReviewNavigationStore(
    (s) => s.activeFilePaths[taskId] ?? null,
  );

  const effectiveFiles = changedFiles;

  const renderFile = useCallback(
    (file: ChangedFile, depth: number) => (
      <ChangedFileItem
        key={file.path}
        file={file}
        taskId={taskId}
        fileKey={file.path}
        isActive={activeFilePath === file.path}
        depth={depth}
      />
    ),
    [taskId, activeFilePath],
  );

  // No branch/PR yet and run is active — show waiting state
  if (!prUrl && !effectiveBranch && effectiveFiles.length === 0) {
    if (isRunActive) {
      return (
        <PanelMessage detail="Changes will appear once the agent starts writing code">
          <Flex align="center" gap="2">
            <Spinner size="1" />
            <Text className="text-sm">Waiting for changes...</Text>
          </Flex>
        </PanelMessage>
      );
    }
    return <PanelMessage>No file changes yet</PanelMessage>;
  }

  if (isLoading && effectiveFiles.length === 0) {
    return <PanelMessage>Loading changes...</PanelMessage>;
  }

  if (effectiveFiles.length === 0) {
    if (hasError && prUrl) {
      return (
        <PanelMessage>
          <Flex direction="column" align="center" gap="2">
            <Text>Could not load file changes</Text>
            <Button size="1" variant="soft" asChild>
              <a href={prUrl} target="_blank" rel="noopener noreferrer">
                View on GitHub
              </a>
            </Button>
          </Flex>
        </PanelMessage>
      );
    }
    if (prUrl) {
      return <PanelMessage>No file changes in pull request</PanelMessage>;
    }
    if (isRunActive) {
      return (
        <PanelMessage detail="Changes will appear as the agent modifies files">
          <Flex align="center" gap="2">
            <Spinner size="1" />
            <Text className="text-sm">Waiting for changes...</Text>
          </Flex>
        </PanelMessage>
      );
    }
    return <PanelMessage>No file changes yet</PanelMessage>;
  }

  return (
    <Box height="100%" overflowY="auto" py="2" id="changes-panel-cloud">
      <Flex direction="column">
        <ChangesTreeView files={effectiveFiles} renderFile={renderFile} />
        {isRunActive && (
          <Flex align="center" gap="2" px="3" py="2">
            <Spinner size="1" />
            <Text color="gray" className="text-[13px]">
              Agent is still running...
            </Text>
          </Flex>
        )}
      </Flex>
    </Box>
  );
}

export function ChangesPanel({ taskId, task }: ChangesPanelProps) {
  const isCloud = useIsCloudTask(taskId);

  if (isCloud) {
    return <CloudChangesPanel taskId={taskId} task={task} />;
  }

  return <LocalChangesPanel taskId={taskId} task={task} />;
}

function LocalChangesPanel({ taskId, task }: ChangesPanelProps) {
  const { effectiveSource, prUrl, linkedBranch } =
    useEffectiveDiffSource(taskId);
  const repoPath = useCwd(taskId);

  if (effectiveSource === "branch") {
    return (
      <BranchChangesPanel
        taskId={taskId}
        repoPath={repoPath}
        branch={linkedBranch}
      />
    );
  }

  if (effectiveSource === "pr") {
    return <PrChangesPanel taskId={taskId} prUrl={prUrl} />;
  }

  return <LocalWorkingTreeChangesPanel taskId={taskId} task={task} />;
}

function LocalWorkingTreeChangesPanel({
  taskId,
  task: _task,
}: ChangesPanelProps) {
  const workspace = useWorkspace(taskId);
  const repoPath = useCwd(taskId);
  const activeFilePath = useReviewNavigationStore(
    (s) => s.activeFilePaths[taskId] ?? null,
  );
  const { changedFiles, changesLoading: isLoading } = useGitQueries(repoPath);
  const handleStageToggle = useStageToggle(repoPath);
  const handleDiscard = useDiscardFile(repoPath);

  const { stagedFiles, unstagedFiles } = useMemo(
    () => partitionByStaged(changedFiles),
    [changedFiles],
  );

  const hasStagedFiles = stagedFiles.length > 0;

  const renderLocalFile = useCallback(
    (file: ChangedFile, depth: number) => {
      const key = makeFileKey(file.staged, file.path);
      return (
        <ChangedFileItem
          key={key}
          file={file}
          taskId={taskId}
          fileKey={key}
          repoPath={repoPath}
          isActive={activeFilePath === key}
          mainRepoPath={workspace?.folderPath}
          onStageToggle={handleStageToggle}
          onDiscard={handleDiscard}
          depth={depth}
        />
      );
    },
    [
      taskId,
      repoPath,
      activeFilePath,
      workspace?.folderPath,
      handleStageToggle,
      handleDiscard,
    ],
  );

  if (!repoPath) {
    return <PanelMessage>No repository path available</PanelMessage>;
  }

  if (isLoading) {
    return <PanelMessage>Loading changes...</PanelMessage>;
  }

  const hasChanges = changedFiles.length > 0;

  if (!hasChanges) {
    return (
      <Box height="100%" overflowY="auto" py="2">
        <Flex direction="column" height="100%">
          <PanelMessage>No file changes yet</PanelMessage>
        </Flex>
      </Box>
    );
  }

  const fileGroups: { files: ChangedFile[]; header?: string }[] = hasStagedFiles
    ? [
        { files: stagedFiles, header: "Staged Changes" },
        { files: unstagedFiles, header: "Changes" },
      ]
    : [{ files: changedFiles }];

  return (
    <Box height="100%" overflowY="auto" py="2" id="changes-panel-local">
      <Flex direction="column">
        {fileGroups.map(({ files, header }) => (
          <Fragment key={header ?? "all"}>
            {header && (
              <Flex px="2" py="1" className="select-none">
                <Text color="gray" className="font-medium text-[13px]">
                  {header} ({files.length})
                </Text>
              </Flex>
            )}
            <ChangesTreeView files={files} renderFile={renderLocalFile} />
          </Fragment>
        ))}
      </Flex>
    </Box>
  );
}

interface RemoteChangesListProps {
  taskId: string;
  files: ChangedFile[];
  isLoading: boolean;
  emptyMessage: string;
  panelId: string;
}

function RemoteChangesList({
  taskId,
  files,
  isLoading,
  emptyMessage,
  panelId,
}: RemoteChangesListProps) {
  const activeFilePath = useReviewNavigationStore(
    (s) => s.activeFilePaths[taskId] ?? null,
  );

  const renderFile = useCallback(
    (file: ChangedFile, depth: number) => (
      <ChangedFileItem
        key={file.path}
        file={file}
        taskId={taskId}
        fileKey={file.path}
        isActive={activeFilePath === file.path}
        depth={depth}
      />
    ),
    [taskId, activeFilePath],
  );

  if (isLoading && files.length === 0) {
    return <PanelMessage>Loading changes...</PanelMessage>;
  }

  if (files.length === 0) {
    return <PanelMessage>{emptyMessage}</PanelMessage>;
  }

  return (
    <Box height="100%" overflowY="auto" py="2" id={panelId}>
      <Flex direction="column">
        <ChangesTreeView files={files} renderFile={renderFile} />
      </Flex>
    </Box>
  );
}

function BranchChangesPanel({
  taskId,
  repoPath,
  branch,
}: {
  taskId: string;
  repoPath: string | undefined;
  branch: string | null;
}) {
  const { data: files = [], isLoading } = useLocalBranchChangedFiles(
    repoPath ?? null,
    branch,
  );

  if (!repoPath || !branch) {
    return <PanelMessage>No branch selected</PanelMessage>;
  }

  return (
    <RemoteChangesList
      taskId={taskId}
      files={files}
      isLoading={isLoading}
      emptyMessage="No file changes in branch"
      panelId="changes-panel-branch"
    />
  );
}

function PrChangesPanel({
  taskId,
  prUrl,
}: {
  taskId: string;
  prUrl: string | null;
}) {
  const { data: files = [], isLoading } = usePrChangedFiles(prUrl);

  if (!prUrl) {
    return <PanelMessage>No pull request linked</PanelMessage>;
  }

  return (
    <RemoteChangesList
      taskId={taskId}
      files={files}
      isLoading={isLoading}
      emptyMessage="No file changes in pull request"
      panelId="changes-panel-pr"
    />
  );
}
