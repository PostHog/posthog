import { ArrowClockwise, Warning } from "@phosphor-icons/react";
import {
  Button,
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { Component, type ErrorInfo, type ReactNode } from "react";

export interface ErrorBoundaryProps {
  children: ReactNode;
  fallback?: ReactNode;
  /** Optional name to identify which boundary caught the error */
  name?: string;
  /** When this value changes, the boundary clears its error state. */
  resetKey?: unknown;
  /**
   * If returns true for a caught error, the boundary renders nothing,
   * skips the fallback UI, and waits for `resetKey` to change before
   * recovering. Use to handle transient errors that the surrounding tree
   * will resolve (e.g. auth state about to flip to unauthenticated).
   */
  shouldSuppress?: (error: Error) => boolean;
  /**
   * Called when an error is caught, before rendering. The host wires this to
   * its telemetry/logging; the primitive itself stays host-agnostic.
   * `suppressed` is true when `shouldSuppress` matched the error.
   */
  onError?: (
    error: Error,
    info: { componentStack?: string | null; suppressed: boolean },
  ) => void;
}

interface State {
  error: Error | null;
  lastResetKey: unknown;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, State> {
  state: State = { error: null, lastResetKey: this.props.resetKey };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(
    props: ErrorBoundaryProps,
    state: State,
  ): Partial<State> | null {
    if (props.resetKey === state.lastResetKey) return null;
    return { error: null, lastResetKey: props.resetKey };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    const suppressed = this.props.shouldSuppress?.(error) ?? false;
    this.props.onError?.(error, {
      componentStack: errorInfo.componentStack,
      suppressed,
    });
  }

  handleRefresh = () => {
    window.location.reload();
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.shouldSuppress?.(error)) return null;
    if (this.props.fallback) return this.props.fallback;

    const details =
      error.stack || error.message || "No error details are available.";

    return (
      <Empty
        role="alert"
        className="min-h-64 border-0 bg-transparent px-6 py-10"
      >
        <EmptyHeader>
          <EmptyMedia variant="icon" className="text-destructive">
            <Warning weight="fill" />
          </EmptyMedia>
          <EmptyTitle>PostHog ran into an error</EmptyTitle>
          <EmptyDescription>
            Refresh the app to continue. If the error comes back, show the
            details and send them to an engineer.
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent className="max-w-lg">
          <Button
            type="button"
            variant="primary"
            data-attr="error-boundary-refresh"
            onClick={this.handleRefresh}
          >
            <ArrowClockwise />
            Refresh
          </Button>
          <Collapsible className="w-full bg-transparent text-left hover:bg-transparent data-open:bg-transparent">
            <CollapsibleTrigger
              data-attr="error-boundary-details"
              className="justify-center"
            >
              Show error details
            </CollapsibleTrigger>
            <CollapsibleContent>
              <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-muted p-3 font-mono text-muted-foreground text-xs">
                {details}
              </pre>
            </CollapsibleContent>
          </Collapsible>
        </EmptyContent>
      </Empty>
    );
  }
}
