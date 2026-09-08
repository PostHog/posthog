import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import {
  describeGithubConnectError,
  GITHUB_CONNECT_TIMEOUT_MESSAGE,
  GITHUB_INSTALL_PENDING_MESSAGE,
} from "@posthog/core/integrations/connectErrors";
import {
  AlertDialog,
  AlertDialogContent,
  AlertDialogFooter,
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { useAuthStateValue } from "@posthog/ui/features/auth/store";
import { GithubConnectionIcon } from "@posthog/ui/features/integrations/components/GithubConnectionIcon";
import { useGithubConnect } from "@posthog/ui/features/integrations/useGithubUserConnect";
import { useRepositoryIntegration } from "@posthog/ui/features/integrations/useIntegrations";
import { useRendererWindowFocusStore } from "@posthog/ui/shell/rendererWindowFocusStore";
import { openUrlInBrowser } from "@posthog/ui/utils/browser";
import { useReducedMotion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";

const GITHUB_DOCS_URL = "https://posthog.com/docs/libraries/github?tab=Desktop";
const FOCUS_SUCCESS_DELAY_MS = 500;
const CONNECTED_SEQUENCE_MS = 1_200;

interface CloudGithubSetupDialogProps {
  hasGithubIntegration?: boolean;
  onConnected: () => void;
  onClose: () => void;
}

export function CloudGithubSetupDialog({
  hasGithubIntegration,
  onConnected,
  onClose,
}: CloudGithubSetupDialogProps) {
  const projectId = useAuthStateValue((state) => state.currentProjectId);
  const cloudRegion = useAuthStateValue((state) => state.cloudRegion);
  const { hasGithubIntegration: hasTeamGithubIntegration } =
    useRepositoryIntegration();
  const windowFocused = useRendererWindowFocusStore((state) => state.focused);
  const shouldReduceMotion = useReducedMotion() === true;
  const [connectCallbackReceived, setConnectCallbackReceived] = useState(false);
  const [connectionStarted, setConnectionStarted] = useState(false);
  const [showConnectedAnimation, setShowConnectedAnimation] = useState(false);
  const didCompleteRef = useRef(false);
  const didNotifyConnectedRef = useRef(false);
  const handleConnectCallback = useCallback(() => {
    setConnectCallbackReceived(true);
  }, []);
  const {
    error,
    isConnecting,
    isTimedOut,
    hasError,
    isPending,
    connect,
    reset,
  } = useGithubConnect({
    projectId,
    projectHasTeamIntegration: hasTeamGithubIntegration,
    onConnected: handleConnectCallback,
  });
  const canConnect = projectId != null && cloudRegion != null;

  const connectionConfirmed =
    connectCallbackReceived || hasGithubIntegration === true;

  useEffect(() => {
    if (!connectionConfirmed || !windowFocused || didCompleteRef.current) {
      return;
    }

    const timer = window.setTimeout(() => {
      didCompleteRef.current = true;
      reset();
      setConnectionStarted(false);
      setShowConnectedAnimation(true);
    }, FOCUS_SUCCESS_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [connectionConfirmed, reset, windowFocused]);

  useEffect(() => {
    if (!showConnectedAnimation || didNotifyConnectedRef.current) return;

    const timer = window.setTimeout(
      () => {
        didNotifyConnectedRef.current = true;
        onConnected();
      },
      shouldReduceMotion ? 0 : CONNECTED_SEQUENCE_MS,
    );
    return () => window.clearTimeout(timer);
  }, [onConnected, shouldReduceMotion, showConnectedAnimation]);

  const handleConnect = useCallback(async () => {
    if (!canConnect) return;
    setConnectionStarted(true);
    await connect();
  }, [canConnect, connect]);

  const handleClose = useCallback(() => {
    if (showConnectedAnimation && !didNotifyConnectedRef.current) {
      didNotifyConnectedRef.current = true;
      onConnected();
    }
    reset();
    setConnectCallbackReceived(false);
    setConnectionStarted(false);
    setShowConnectedAnimation(false);
    onClose();
  }, [onClose, onConnected, reset, showConnectedAnimation]);

  const connectionMessage = hasError
    ? describeGithubConnectError(error)
    : isTimedOut
      ? GITHUB_CONNECT_TIMEOUT_MESSAGE
      : isPending
        ? GITHUB_INSTALL_PENDING_MESSAGE
        : null;
  const waitingForGithub =
    (connectionStarted || isConnecting) &&
    !hasError &&
    !isTimedOut &&
    !isPending &&
    !showConnectedAnimation;

  return (
    <AlertDialog open onOpenChange={() => undefined}>
      <AlertDialogContent>
        <div className="p-2">
          <Empty className="py-6" aria-live="polite">
            <EmptyHeader>
              <EmptyMedia>
                <GithubConnectionIcon
                  connected={showConnectedAnimation}
                  loading={waitingForGithub}
                />
              </EmptyMedia>
              <EmptyTitle>
                {showConnectedAnimation
                  ? "GitHub connected"
                  : waitingForGithub
                    ? "Waiting for GitHub"
                    : "GitHub authentication required"}
              </EmptyTitle>
              <EmptyDescription
                className={
                  hasError || isTimedOut ? "text-destructive" : undefined
                }
              >
                {showConnectedAnimation
                  ? "You're ready to use Cloud tasks."
                  : waitingForGithub
                    ? "Finish authorizing in your browser, then return here."
                    : (connectionMessage ??
                      "Cloud tasks require GitHub authentication.")}
              </EmptyDescription>
            </EmptyHeader>
            {!showConnectedAnimation && (
              <EmptyContent className="flex-row justify-center gap-2">
                <Button
                  type="button"
                  variant="primary"
                  loading={waitingForGithub}
                  disabled={!canConnect || waitingForGithub}
                  onClick={() => void handleConnect()}
                >
                  {hasError || isTimedOut ? "Try again" : "Connect GitHub"}
                </Button>
                <Button
                  type="button"
                  variant="link-muted"
                  onClick={() => void openUrlInBrowser(GITHUB_DOCS_URL)}
                >
                  Learn more
                  <ArrowSquareOutIcon size={12} />
                </Button>
              </EmptyContent>
            )}
          </Empty>
        </div>

        <AlertDialogFooter>
          <Button
            type="button"
            variant={showConnectedAnimation ? "primary" : "outline"}
            onClick={handleClose}
          >
            {showConnectedAnimation ? "Close" : "Cancel"}
          </Button>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
