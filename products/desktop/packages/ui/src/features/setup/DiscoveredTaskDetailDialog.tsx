import { PlusIcon, SparkleIcon } from "@phosphor-icons/react";
import { buildDiscoveredTaskPrompt } from "@posthog/core/setup/buildDiscoveredTaskPrompt";
import type { DiscoveredTask } from "@posthog/core/setup/types";
import {
  Button,
  Dialog,
  DialogBody,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { openTaskInput } from "@posthog/ui/router/useOpenTask";
import { Badge } from "../../primitives/Badge";
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
      <DialogContent className="max-w-[640px]">
        {task && <DiscoveredTaskDetailContent task={task} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function DiscoveredTaskDetailContent({
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
            color="violet"
            className="!leading-none inline-flex shrink-0 items-center gap-1"
          >
            <SparkleIcon size={10} weight="fill" />
            Suggested
          </Badge>
          <DialogTitle className="min-w-0 text-balance break-words text-base">
            {task.title}
          </DialogTitle>
        </div>
      </DialogHeader>

      <DialogBody className="flex flex-col gap-4">
        <div className="max-h-[60vh] min-h-0 overflow-y-auto pr-3">
          <div className="flex flex-col gap-4">
            <div className="flex items-center gap-2 text-(--gray-11)">
              <span style={{ color: `var(--${config.color}-9)` }}>
                <CategoryIcon size={14} weight="duotone" />
              </span>
              <span className="text-xs uppercase tracking-wide">
                {config.label}
              </span>
              {task.file && (
                <>
                  <span className="text-(--gray-8) text-xs">·</span>
                  <span className="break-all font-mono text-xs">
                    {task.file}
                    {task.lineHint ? `:${task.lineHint}` : ""}
                  </span>
                </>
              )}
            </div>

            <ProseSection content={task.description} />

            {task.impact && (
              <section>
                <h2 className="mb-1 font-medium text-(--gray-11) text-xs uppercase tracking-wide">
                  Why it matters
                </h2>
                <ProseSection content={task.impact} />
              </section>
            )}

            {task.recommendation && (
              <section>
                <h2 className="mb-1 font-medium text-(--gray-11) text-xs uppercase tracking-wide">
                  Suggested approach
                </h2>
                <ProseSection content={task.recommendation} />
              </section>
            )}

            <p className="text-(--gray-10) text-xs italic">
              Suggested locally from a quick scan of your codebase. Open it as a
              task to investigate and fix.
            </p>
          </div>
        </div>
      </DialogBody>

      <DialogFooter>
        <Button variant="outline" size="sm" onClick={handleDismiss}>
          Dismiss
        </Button>
        <Button variant="primary" size="sm" onClick={handleCreateTask}>
          <PlusIcon size={14} weight="bold" />
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
