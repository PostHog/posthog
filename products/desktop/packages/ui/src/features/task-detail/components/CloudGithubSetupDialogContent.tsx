import { GITHUB_CODE_CONTEXT_MESSAGE } from "@posthog/core/integrations/connectErrors";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@posthog/quill";
import { GithubConnectionIcon } from "@posthog/ui/features/integrations/components/GithubConnectionIcon";
import type { ReactElement } from "react";

interface CloudGithubSetupDialogContentProps {
  connected: boolean;
  loading: boolean;
  hasError: boolean;
  isTimedOut: boolean;
  canConnect: boolean;
  connectionMessage?: string;
  onConnect: () => void;
  onOpenPermissions: () => void;
  onClose: () => void;
}

export function CloudGithubSetupDialogContent({
  connected,
  loading,
  hasError,
  isTimedOut,
  canConnect,
  connectionMessage,
  onConnect,
  onOpenPermissions,
  onClose,
}: CloudGithubSetupDialogContentProps): ReactElement {
  const title = connected
    ? "GitHub connected"
    : loading
      ? "Waiting for GitHub"
      : "Connect GitHub to run in the cloud";
  const description = connected
    ? "You are ready to run cloud tasks."
    : loading
      ? "Finish authorizing in your browser, then return here."
      : (connectionMessage ??
        `To run this task in the cloud, ${GITHUB_CODE_CONTEXT_MESSAGE}`);

  return (
    <Dialog
      open
      onOpenChange={(nextOpen) => {
        // A backdrop press or Escape while the browser authorization is in
        // flight discards the run location the user picked, even though GitHub
        // still connects. Only the buttons end that wait.
        if (!nextOpen && !loading) onClose();
      }}
    >
      <DialogContent className="max-w-sm" showCloseButton={false}>
        {/* The dialog role speaks the title and description once, on open, so
            the later waiting, error and connected states need a live region. */}
        <DialogHeader className="items-center text-center" aria-live="polite">
          <GithubConnectionIcon connected={connected} loading={loading} />
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription
            className={hasError || isTimedOut ? "text-destructive" : undefined}
          >
            {description}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col items-center gap-2">
          {!connected ? (
            <>
              <Button
                type="button"
                variant="primary"
                loading={loading}
                disabled={!canConnect || loading}
                onClick={onConnect}
              >
                {hasError || isTimedOut ? "Try again" : "Connect GitHub"}
              </Button>
              <Button
                type="button"
                variant="link-muted"
                data-attr="github-permissions"
                onClick={onOpenPermissions}
              >
                What permissions does this grant?
              </Button>
              <Button
                type="button"
                variant="link-muted"
                data-attr="github-setup-not-now"
                onClick={onClose}
              >
                Not now
              </Button>
            </>
          ) : (
            <Button type="button" variant="primary" onClick={onClose}>
              Close
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
