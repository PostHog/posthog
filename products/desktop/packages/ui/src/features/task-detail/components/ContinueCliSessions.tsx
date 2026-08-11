import { MagnifyingGlassIcon } from "@phosphor-icons/react";
import {
  TASK_SERVICE,
  type TaskService,
} from "@posthog/core/task-detail/taskService";
import { useService } from "@posthog/di/react";
import {
  ANALYTICS_EVENTS,
  type ClaudeSessionImportSource,
  formatRelativeTimeShort,
  type WorkspaceMode,
} from "@posthog/shared";
import { openTask } from "@posthog/ui/router/useOpenTask";
import { track } from "@posthog/ui/shell/analytics";
import {
  Dialog,
  Flex,
  ScrollArea,
  Spinner,
  Text,
  TextField,
} from "@radix-ui/themes";
import { useEffect, useState } from "react";
import claudeMark from "../../../assets/services/claude.svg";
import { toastError } from "../../notifications/errorDetails";
import { useCreateTask } from "../../tasks/useTaskCrudMutations";
import { useClaudeCliSessions } from "../hooks/useClaudeCliSessions";
import { SuggestedTasksPanel } from "./SuggestedTasksPanel";

export interface CliSession {
  sourceSessionId: string;
  title: string | null;
  lastPrompt: string | null;
  updatedAt: string;
  gitBranch: string | null;
  status: "new" | "imported" | "updated";
}

function sessionLabel(session: CliSession): string {
  return (
    session.title?.trim() ||
    session.lastPrompt?.trim() ||
    "Untitled Claude Code session"
  );
}

/** "feat/auth · 2h" — branch and recency, omitting whichever is missing. */
function sessionMeta(session: CliSession): string {
  return [session.gitBranch, formatRelativeTimeShort(session.updatedAt)]
    .filter(Boolean)
    .join(" · ");
}

interface SessionCardProps {
  session: CliSession;
  meta: string;
  running?: boolean;
  disabled?: boolean;
  showHelpText?: boolean;
  onClick: () => void;
}

/** One session as a clickable card. Shared by the inline lead-in and the dialog. */
function SessionCard({
  session,
  meta,
  running,
  disabled,
  showHelpText,
  onClick,
}: SessionCardProps) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      className="flex w-full cursor-pointer items-start gap-2.5 rounded-xl border border-(--gray-a3) bg-(--color-panel-solid) px-2.5 py-2 text-left shadow-[0_1px_3px_rgba(0,0,0,0.04),0_1px_2px_rgba(0,0,0,0.02)] transition-[border-color,box-shadow] hover:border-(--card-hover-border) hover:shadow-[0_2px_8px_rgba(0,0,0,0.06),0_1px_3px_rgba(0,0,0,0.04)] disabled:cursor-not-allowed disabled:opacity-60"
      style={
        { "--card-hover-border": "var(--orange-6)" } as React.CSSProperties
      }
    >
      <Flex
        align="center"
        justify="center"
        className="h-6 w-6 shrink-0 rounded-md"
        style={{ backgroundColor: "var(--orange-3)" }}
      >
        {running ? (
          <Spinner size="1" />
        ) : (
          <img src={claudeMark} alt="" className="h-3.5 w-3.5" />
        )}
      </Flex>
      <Flex direction="column" gap="1" className="min-w-0 flex-1">
        <Flex direction="row" gap="1" align="center" className="min-w-0">
          <Text
            size="1"
            weight="medium"
            className="min-w-0 truncate text-(--gray-12)"
          >
            {sessionLabel(session)}
          </Text>
          {showHelpText && (
            <Text
              size="1"
              className="shrink-0 whitespace-nowrap text-(--gray-11) leading-normal"
            >
              · from Claude Code
            </Text>
          )}
        </Flex>
        {meta && (
          <Text
            size="1"
            className="line-clamp-1 text-(--gray-11) leading-normal"
          >
            {meta}
          </Text>
        )}
      </Flex>
    </button>
  );
}

interface SessionPickerDialogProps {
  sessions: CliSession[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  runningId: string | null;
  disabled?: boolean;
  onContinue: (session: CliSession) => void;
}

/**
 * The full archive behind the inline lead-in: a searchable list, so the surface
 * scales to a repo with hundreds of past sessions (you filter, never scroll).
 */
export function SessionPickerDialog({
  sessions,
  open,
  onOpenChange,
  runningId,
  disabled,
  onContinue,
}: SessionPickerDialogProps) {
  const [query, setQuery] = useState("");
  const q = query.trim().toLowerCase();
  const filtered = q
    ? sessions.filter((s) =>
        [s.title, s.lastPrompt, s.gitBranch].some((field) =>
          field?.toLowerCase().includes(q),
        ),
      )
    : sessions;

  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Content size="2" maxWidth="520px">
        <Dialog.Title size="3">Continue a Claude Code session</Dialog.Title>
        <Dialog.Description size="1" color="gray" mb="3">
          Pick up a recent terminal session in this repo.
        </Dialog.Description>
        <TextField.Root
          placeholder="Search sessions…"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          mb="3"
        >
          <TextField.Slot>
            <MagnifyingGlassIcon size={14} />
          </TextField.Slot>
        </TextField.Root>
        <ScrollArea
          type="auto"
          scrollbars="vertical"
          style={{ maxHeight: 360 }}
        >
          <Flex direction="column" gap="2" pr="3">
            {filtered.map((session) => (
              <SessionCard
                key={session.sourceSessionId}
                session={session}
                meta={sessionMeta(session)}
                running={runningId === session.sourceSessionId}
                disabled={disabled || !!runningId}
                onClick={() => onContinue(session)}
              />
            ))}
            {filtered.length === 0 && (
              <Text size="1" color="gray" className="px-1 py-6 text-center">
                No matching sessions.
              </Text>
            )}
          </Flex>
        </ScrollArea>
      </Dialog.Content>
    </Dialog.Root>
  );
}

interface ContinueCliSessionsInlineProps {
  sessions: CliSession[];
  runningId: string | null;
  disabled?: boolean;
  onContinue: (session: CliSession, source: ClaudeSessionImportSource) => void;
}

/**
 * The Claude Code resume entry: the most recent session as a single card (the
 * "Claude Code ·" provenance lives on the card), plus a "See all" into the
 * searchable archive when there's more than one. Rendered as the first item of
 * the suggestions list — no header of its own.
 */
export function ContinueCliSessionsInline({
  sessions,
  runningId,
  disabled,
  onContinue,
}: ContinueCliSessionsInlineProps) {
  const [pickerOpen, setPickerOpen] = useState(false);
  if (sessions.length === 0) return null;

  const [latest] = sessions;

  return (
    <>
      <Flex gap="2" align="center">
        <div className="min-w-0 flex-1">
          <SessionCard
            session={latest}
            meta={sessionMeta(latest)}
            running={runningId === latest.sourceSessionId}
            disabled={disabled || !!runningId}
            showHelpText
            onClick={() => onContinue(latest, "inline_card")}
          />
        </div>
        {sessions.length > 1 && (
          <button
            type="button"
            onClick={() => setPickerOpen(true)}
            className="shrink-0 cursor-pointer rounded-md border border-(--gray-a4) bg-(--color-panel-solid) px-2 py-1 text-(--gray-11) text-[11px] hover:border-(--gray-7) hover:text-(--gray-12)"
          >
            + {sessions.length - 1}
          </button>
        )}
      </Flex>
      <SessionPickerDialog
        sessions={sessions}
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        runningId={runningId}
        disabled={disabled}
        onContinue={(session) => {
          setPickerOpen(false);
          onContinue(session, "picker_dialog");
        }}
      />
    </>
  );
}

interface NewTaskSuggestionsProps {
  repoPath: string | null;
  workspaceMode: WorkspaceMode;
  disabled?: boolean;
}

/**
 * Repos whose "Claude Code sessions shown" event has already fired this app
 * session. Module-level so it outlives NewTaskSuggestions remounts (navigating
 * away and back), keeping the funnel top at one impression per repo per session
 * rather than one per mount.
 */
const shownRepos = new Set<string>();

/**
 * The new-task suggestions panel with the Claude Code resume card injected as
 * the first item, so CLI sessions live inside the single "Suggestions" list
 * rather than as a separate section. Clicking the card imports its transcript
 * and opens the new task.
 */
export function NewTaskSuggestions({
  repoPath,
  workspaceMode,
  disabled,
}: NewTaskSuggestionsProps) {
  // Imports always resume against the main repo checkout, so the card shows for
  // any non-cloud mode; the created task itself runs in local mode.
  const enabled = workspaceMode !== "cloud";
  const query = useClaudeCliSessions(repoPath, enabled);
  const taskService = useService<TaskService>(TASK_SERVICE);
  const { invalidateTasks } = useCreateTask();
  const [runningId, setRunningId] = useState<string | null>(null);

  // Hide sessions already imported and unchanged — they're a task now. One
  // reappears only when its CLI transcript changes again (status "updated").
  const sessions =
    enabled && repoPath
      ? ((query.data?.sessions ?? []) as CliSession[]).filter(
          (session) => session.status !== "imported",
        )
      : [];

  // The top of the import funnel: fire once per repo when resumable sessions
  // first surface, so we can measure how many of these lead-ins convert.
  useEffect(() => {
    if (!repoPath || sessions.length === 0 || shownRepos.has(repoPath)) {
      return;
    }
    shownRepos.add(repoPath);
    track(ANALYTICS_EVENTS.CLAUDE_SESSIONS_SHOWN, {
      sessions_count: sessions.length,
    });
  }, [repoPath, sessions.length]);

  const handleContinue = async (
    session: CliSession,
    source: ClaudeSessionImportSource,
  ) => {
    if (runningId || !repoPath) return;
    setRunningId(session.sourceSessionId);
    try {
      const result = await taskService.createTask(
        {
          repoPath,
          workspaceMode: "local",
          taskDescription: sessionLabel(session),
          importedClaudeSession: {
            sourceSessionId: session.sourceSessionId,
            branch: session.gitBranch,
          },
        },
        (output) => {
          invalidateTasks(output.task);
          void openTask(output.task);
        },
      );
      if (result.success) {
        track(ANALYTICS_EVENTS.CLAUDE_SESSION_IMPORTED, {
          source,
          session_status: session.status,
          has_git_branch: !!session.gitBranch,
          sessions_available_count: sessions.length,
        });
      } else {
        track(ANALYTICS_EVENTS.CLAUDE_SESSION_IMPORT_FAILED, {
          source,
          session_status: session.status,
          failed_step: result.failedStep,
        });
        toastError("Couldn't continue Claude Code session", result.error);
      }
    } finally {
      setRunningId(null);
      void query.refetch();
    }
  };

  return (
    <SuggestedTasksPanel
      leading={
        sessions.length > 0 ? (
          <ContinueCliSessionsInline
            sessions={sessions}
            runningId={runningId}
            disabled={disabled}
            onContinue={handleContinue}
          />
        ) : null
      }
    />
  );
}
