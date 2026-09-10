import {
  Button,
  Empty,
  EmptyContent,
  EmptyDescription,
  EmptyHeader,
  EmptyMedia,
  EmptyTitle,
} from "@posthog/quill";
import { sleepingHog } from "@posthog/ui/assets/hedgehogs";
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

  handleRetry = () => {
    this.setState({ error: null });
  };

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    if (this.props.shouldSuppress?.(error)) return null;
    if (this.props.fallback) return this.props.fallback;

    return (
      <Empty className="h-full min-h-64 border-0 p-4" role="alert">
        <EmptyHeader>
          <EmptyMedia className="mb-2">
            <img src={sleepingHog} alt="" className="h-auto w-64 max-w-full" />
          </EmptyMedia>
          <EmptyTitle>Something went wrong</EmptyTitle>
          <EmptyDescription className="break-words">
            {error.message || "An unexpected error occurred"}
          </EmptyDescription>
        </EmptyHeader>
        <EmptyContent>
          <Button size="default" variant="primary" onClick={this.handleRetry}>
            Try again
          </Button>
        </EmptyContent>
      </Empty>
    );
  }
}
