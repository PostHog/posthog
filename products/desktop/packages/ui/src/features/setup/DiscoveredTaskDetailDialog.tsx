import { PlusIcon, SparkleIcon } from "@phosphor-icons/react";
import { buildDiscoveredTaskPrompt } from "@posthog/core/setup/buildDiscoveredTaskPrompt";
import type { DiscoveredTask } from "@posthog/core/setup/types";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import {
  Box,
  Dialog,
  Flex,
  ScrollArea,
  Text,
  VisuallyHidden,
} from "@radix-ui/themes";
import { Badge } from "../../primitives/Badge";
import { Button } from "../../primitives/Button";
import { useActiveRepoStore } from "../../shell/activeRepoStore";
import { track } from "../../shell/analytics";
import { MarkdownRenderer } from "../editor/components/MarkdownRenderer";
import { useFolders } from "../folders/useFolders";
import { useDetectedCloudRepository } from "../repo-files/useDetectedCloudRepository";
import { CATEGORY_CONFIG, FALLBACK_CATEGORY_CONFIG } from "./categoryConfig";
import { isTaskForRepo, useSetupStore } from "./setupStore";

interface DiscoveredTaskDetailDialogProps {
  task: DiscoveredTask | null;
  onClose: () => void;
}

export function DiscoveredTaskDetailDialog({
  task,
  onClose,
}: DiscoveredTaskDetailDialogProps) {
  return (
    <Dialog.Root
      open={task !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <Dialog.Content maxWidth="640px">
        <VisuallyHidden>
          <Dialog.Title>{task?.title ?? "Suggestion"}</Dialog.Title>
        </VisuallyHidden>
        {task && <DialogBody task={task} onClose={onClose} />}
      </Dialog.Content>
    </Dialog.Root>
  );
}

function DialogBody({
  task,
  onClose,
}: {
  task: DiscoveredTask;
  onClose: () => void;
}) {
  const config = CATEGORY_CONFIG[task.category] ?? FALLBACK_CATEGORY_CONFIG;
  const CategoryIcon = config.icon;

  const tasks = useSetupStore((s) =>
    s.discoveredTasks.filter((t) => isTaskForRepo(t, task.repoPath ?? null)),
  );
  const selectedDirectory = useActiveRepoStore((s) => s.path);
  const { folders } = useFolders();
  const detectedCloudRepository = useDetectedCloudRepository(selectedDirectory);

  const handleCreateTask = () => {
    const position = tasks.findIndex((t) => t.id === task.id);
    track(ANALYTICS_EVENTS.SETUP_TASK_SELECTED, {
      discovered_task_id: task.id,
      category: task.category,
      position: position >= 0 ? position : 0,
      total_discovered: tasks.length,
    });

    const initialPrompt = buildDiscoveredTaskPrompt(task);
    const folderId = folders.find((f) => f.path === selectedDirectory)?.id;
    useSetupStore
      .getState()
      .removeDiscoveredTask(task.id, task.repoPath ?? null);
    onClose();
    openTaskInput({
      initialPrompt,
      folderId,
      initialCloudRepository: detectedCloudRepository ?? undefined,
    });
  };

  const handleDismiss = () => {
    const position = tasks.findIndex((t) => t.id === task.id);
    track(ANALYTICS_EVENTS.SETUP_TASK_DISMISSED, {
      discovered_task_id: task.id,
      category: task.category,
      position: position >= 0 ? position : 0,
      total_discovered: tasks.length,
    });
    useSetupStore
      .getState()
      .removeDiscoveredTask(task.id, task.repoPath ?? null);
    onClose();
  };

  return (
    <Flex direction="column" gap="4">
      <Flex align="center" gap="2" wrap="wrap">
        <Badge
          color="violet"
          className="!leading-none inline-flex shrink-0 items-center gap-1"
        >
          <SparkleIcon size={10} weight="fill" />
          Suggested
        </Badge>
        <Text className="block min-w-0 text-balance break-words font-bold text-base">
          {task.title}
        </Text>
      </Flex>

      <ScrollArea
        type="auto"
        scrollbars="vertical"
        className="max-h-[60vh] min-h-0"
      >
        <Flex direction="column" gap="4" pr="3">
          <Flex align="center" gap="2" className="text-(--gray-11)">
            <span style={{ color: `var(--${config.color}-9)` }}>
              <CategoryIcon size={14} weight="duotone" />
            </span>
            <Text size="1" className="uppercase tracking-wide">
              {config.label}
            </Text>
            {task.file && (
              <>
                <Text size="1" className="text-(--gray-8)">
                  ·
                </Text>
                <Text size="1" className="break-all font-mono">
                  {task.file}
                  {task.lineHint ? `:${task.lineHint}` : ""}
                </Text>
              </>
            )}
          </Flex>

          <ProseSection content={task.description} />

          {task.impact && (
            <Box>
              <Text
                size="1"
                weight="medium"
                className="mb-1 block text-(--gray-11) uppercase tracking-wide"
              >
                Why it matters
              </Text>
              <ProseSection content={task.impact} />
            </Box>
          )}

          {task.recommendation && (
            <Box>
              <Text
                size="1"
                weight="medium"
                className="mb-1 block text-(--gray-11) uppercase tracking-wide"
              >
                Suggested approach
              </Text>
              <ProseSection content={task.recommendation} />
            </Box>
          )}

          <Text size="1" className="text-(--gray-10) italic">
            Suggested locally from a quick scan of your codebase. Open it as a
            task to investigate and fix.
          </Text>
        </Flex>
      </ScrollArea>

      <Flex gap="3" justify="end">
        <Button variant="soft" color="gray" onClick={handleDismiss}>
          Dismiss
        </Button>
        <Button variant="solid" onClick={handleCreateTask}>
          <PlusIcon size={14} weight="bold" />
          Implement as new task
        </Button>
      </Flex>
    </Flex>
  );
}

function ProseSection({ content }: { content: string }) {
  return (
    <Box className="min-w-0 text-pretty break-words text-(--gray-12) text-[13px] [&_*]:leading-relaxed [&_a]:pointer-events-auto [&_code]:font-mono [&_li]:mb-1 [&_p:last-child]:mb-0 [&_p]:mb-2">
      <MarkdownRenderer content={content} />
    </Box>
  );
}
