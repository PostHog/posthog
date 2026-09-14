import { GitBranch, Warning } from "@phosphor-icons/react";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  Button,
} from "@posthog/quill";

interface BranchMismatchDialogProps {
  open: boolean;
  linkedBranch: string;
  currentBranch: string;
  hasUncommittedChanges: boolean;
  switchError: string | null;
  onSwitch: () => void;
  onContinue: () => void;
  onCancel: () => void;
  isSwitching?: boolean;
}

function BranchLabel({ name }: { name: string }) {
  return (
    <code className="inline-flex max-w-full items-center gap-1 overflow-hidden rounded bg-muted px-1.5 py-0.5 text-sm">
      <GitBranch size={12} className="shrink-0" />
      <span className="overflow-hidden text-ellipsis whitespace-nowrap">
        {name}
      </span>
    </code>
  );
}

export function BranchMismatchDialog({
  open,
  linkedBranch,
  currentBranch,
  hasUncommittedChanges,
  switchError,
  onSwitch,
  onContinue,
  onCancel,
  isSwitching,
}: BranchMismatchDialogProps) {
  return (
    <AlertDialog open={open} onOpenChange={() => undefined}>
      <AlertDialogContent className="max-w-[420px]">
        <AlertDialogHeader>
          <AlertDialogTitle>
            <span className="flex items-center gap-2">
              <Warning size={18} weight="fill" color="var(--orange-9)" />
              Wrong branch
            </span>
          </AlertDialogTitle>
          <AlertDialogDescription>
            This task is linked to a different branch than the one you're
            currently on. The agent will make changes on the current branch.
          </AlertDialogDescription>
        </AlertDialogHeader>
        <div className="flex min-w-0 flex-col gap-1">
          <div className="flex min-w-0 items-center gap-2">
            <span className="w-16 shrink-0 text-[13px] text-muted-foreground">
              Linked
            </span>
            <BranchLabel name={linkedBranch} />
          </div>
          <div className="flex min-w-0 items-center gap-2">
            <span className="w-16 shrink-0 text-[13px] text-muted-foreground">
              Current
            </span>
            <BranchLabel name={currentBranch} />
          </div>
        </div>

        {hasUncommittedChanges && !switchError ? (
          <p className="rounded-md border border-border bg-muted p-2 text-muted-foreground text-sm">
            You have uncommitted changes on your current branch. If needed,
            commit or stash them first.
          </p>
        ) : null}

        {switchError ? (
          <p className="rounded-md border border-destructive/30 bg-destructive/10 p-2 text-destructive text-sm">
            {switchError}
          </p>
        ) : null}

        <AlertDialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={isSwitching}>
            Cancel
          </Button>
          <Button variant="outline" onClick={onContinue} disabled={isSwitching}>
            Continue anyway
          </Button>
          <Button
            variant="primary"
            onClick={onSwitch}
            loading={isSwitching}
            disabled={isSwitching}
          >
            Switch branch
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
