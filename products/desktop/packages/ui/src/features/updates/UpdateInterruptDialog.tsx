import {
  computeWorkingLocalSessionsSignature,
  listWorkingLocalSessions,
  type WorkingLocalSession,
} from "@posthog/core/sessions/workingSessions";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";
import { useSessionStore } from "@posthog/ui/features/sessions/sessionStore";
import { useUpdateInterruptStore } from "@posthog/ui/features/updates/updateInterruptStore";
import { Link } from "@tanstack/react-router";
import { useEffect, useMemo } from "react";

function TaskLink({
  task,
  onNavigate,
}: {
  task: WorkingLocalSession;
  onNavigate: () => void;
}) {
  return (
    <Link
      to="/tasks/$taskId"
      params={{ taskId: task.taskId }}
      onClick={onNavigate}
      className="text-accent-11 underline hover:text-accent-12"
    >
      {task.taskTitle}
    </Link>
  );
}

/**
 * Intercepts restart-to-update while local agent turns are in flight: names
 * the tasks a restart would interrupt and offers to cancel, restart once
 * they finish, or restart immediately. Mounted at the root; the armed-wait
 * effect below runs even while the dialog is closed.
 */
export function UpdateInterruptDialog() {
  const isOpen = useUpdateInterruptStore((s) => s.isOpen);
  const waitingForIdle = useUpdateInterruptStore((s) => s.waitingForIdle);
  const runInstall = useUpdateInterruptStore((s) => s.runInstall);
  const wait = useUpdateInterruptStore((s) => s.wait);
  const clear = useUpdateInterruptStore((s) => s.clear);

  const sessions = useSessionStore(
    (s) => s.sessions,
    (a, b) =>
      computeWorkingLocalSessionsSignature(a) ===
      computeWorkingLocalSessionsSignature(b),
  );
  const working = useMemo(() => listWorkingLocalSessions(sessions), [sessions]);

  useEffect(() => {
    if (!waitingForIdle || working.length > 0) return;
    const install = runInstall;
    clear();
    install?.();
  }, [waitingForIdle, working.length, runInstall, clear]);

  const restartNow = () => {
    const install = runInstall;
    clear();
    install?.();
  };

  const single = working.length === 1 ? working[0] : null;

  return (
    <AlertDialog
      open={isOpen}
      onOpenChange={(next) => {
        if (!next) clear();
      }}
    >
      <AlertDialogContent>
        <AlertDialogHeader>
          <AlertDialogTitle>
            {working.length > 1
              ? "Agents are still working"
              : single
                ? "An agent is still working"
                : "Ready to restart"}
          </AlertDialogTitle>
          <AlertDialogDescription>
            {working.length > 1 ? (
              "Agents are working in these tasks. Restarting now will interrupt that work."
            ) : single ? (
              <>
                An agent is working in{" "}
                <TaskLink task={single} onNavigate={clear} />. Restarting now
                will interrupt that work.
              </>
            ) : (
              "The agents finished their work. Restarting will not interrupt anything."
            )}
          </AlertDialogDescription>
          {working.length > 1 ? (
            <ul className="mt-1 flex list-disc flex-col gap-1.5 pl-4">
              {working.map((task) => (
                <li key={task.taskRunId}>
                  <TaskLink task={task} onNavigate={clear} />
                </li>
              ))}
            </ul>
          ) : null}
        </AlertDialogHeader>
        <AlertDialogFooter>
          <Button variant="outline" onClick={clear}>
            Cancel
          </Button>
          {working.length > 0 ? (
            <Button variant="outline" onClick={wait}>
              Restart when finished
            </Button>
          ) : null}
          <Button variant="primary" onClick={restartNow}>
            Restart now
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
