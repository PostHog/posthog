import { PlusIcon, SparkleIcon } from "@phosphor-icons/react";
import { buildDiscoveredTaskPrompt } from "@posthog/core/setup/buildDiscoveredTaskPrompt";
import type { DiscoveredTask } from "@posthog/core/setup/types";
import {
  Badge,
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Text,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
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
    <Dialog
      open={task !== null}
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="max-w-[640px]" showCloseButton={false}>
        {task && <DiscoveredTaskDialogContent task={task} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function DiscoveredTaskDialogContent({
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
    <>
      <DialogHeader>
        <div className="flex flex-wrap items-center gap-2">
          <Badge
            variant="completed"
            className="inline-flex shrink-0 items-center gap-1"
          >
            <SparkleIcon weight="fill" />
            Suggested
          </Badge>
          <DialogTitle className="min-w-0 text-balance break-words">
            {task.title}
          </DialogTitle>
        </div>
      </DialogHeader>

      <DialogBody viewportClassName="flex max-h-[60vh] flex-col gap-4">
        <div className="flex items-center gap-2 text-(--gray-11)">
          <span style={{ color: `var(--${config.color}-9)` }}>
            <CategoryIcon size={14} weight="duotone" />
          </span>
          <Text size="xs" className="uppercase tracking-wide">
            {config.label}
          </Text>
          {task.file && (
            <>
              <Text size="xs" className="text-(--gray-8)">
                ·
              </Text>
              <Text size="xs" className="break-all font-mono">
                {task.file}
                {task.lineHint ? `:${task.lineHint}` : ""}
              </Text>
            </>
          )}
        </div>

        <ProseSection content={task.description} />

        {task.impact && (
          <div className="flex flex-col gap-1">
            <Text size="xs" weight="medium" className="uppercase tracking-wide">
              Why it matters
            </Text>
            <ProseSection content={task.impact} />
          </div>
        )}

        {task.recommendation && (
          <div className="flex flex-col gap-1">
            <Text size="xs" weight="medium" className="uppercase tracking-wide">
              Suggested approach
            </Text>
            <ProseSection content={task.recommendation} />
          </div>
        )}

        <Text size="xs" variant="muted" className="italic">
          Suggested locally from a quick scan of your codebase. Open it as a
          task to investigate and fix.
        </Text>
      </DialogBody>

      <DialogFooter>
        <Button variant="outline" onClick={handleDismiss}>
          Dismiss
        </Button>
        <Button variant="primary" onClick={handleCreateTask}>
          <PlusIcon weight="bold" />
          Implement as new task
        </Button>
      </DialogFooter>
    </>
  );
}

function ProseSection({ content }: { content: string }) {
  return (
    <div className="min-w-0 text-pretty break-words text-(--gray-12) text-[13px] [&_*]:leading-relaxed [&_a]:pointer-events-auto [&_code]:font-mono [&_li]:mb-1 [&_p:last-child]:mb-0 [&_p]:mb-2">
      <MarkdownRenderer content={content} />
    </div>
  );
}
