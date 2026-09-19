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
        "Agents work from the latest code in the repos you authorize. Changes come back as pull requests for you to review.");

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
      <DialogContent className="max-w-sm gap-6 p-4" showCloseButton={false}>
        {/* The dialog role speaks the title and description once, on open, so
            the later waiting, error and connected states need a live region. */}
        <DialogHeader
          className="items-center gap-2 p-0 text-center"
          aria-live="polite"
        >
          <div className="mb-2">
            <GithubConnectionIcon
              connected={connected}
              loading={loading}
              paired
            />
          </div>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription
            className={
              hasError || isTimedOut
                ? "text-balance text-destructive"
                : "text-balance"
            }
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
                className="w-full"
                loading={loading}
                disabled={!canConnect || loading}
                onClick={onConnect}
              >
                {hasError || isTimedOut ? "Try again" : "Connect GitHub"}
              </Button>
              <Button
                type="button"
                variant="default"
                className="w-full text-muted-foreground"
                data-attr="github-setup-not-now"
                onClick={onClose}
              >
                Not now
              </Button>
              <p className="mt-2 text-balance text-center text-muted-foreground text-xs">
                Read and write access to the repos you select.{" "}
                <Button
                  type="button"
                  variant="link-muted"
                  className="inline h-auto p-0 text-xs underline"
                  data-attr="github-permissions"
                  onClick={onOpenPermissions}
                >
                  Details
                </Button>
              </p>
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
