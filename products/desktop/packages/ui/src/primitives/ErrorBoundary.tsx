import { ErrorBoundaryFallback } from "@posthog/ui/primitives/ErrorBoundaryFallback";
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
  componentStack: string | null;
  lastResetKey: unknown;
}

export class ErrorBoundary extends Component<ErrorBoundaryProps, State> {
  state: State = {
    error: null,
    componentStack: null,
    lastResetKey: this.props.resetKey,
  };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  static getDerivedStateFromProps(
    props: ErrorBoundaryProps,
    state: State,
  ): Partial<State> | null {
    if (props.resetKey === state.lastResetKey) return null;
    return { error: null, componentStack: null, lastResetKey: props.resetKey };
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    const suppressed = this.props.shouldSuppress?.(error) ?? false;
    this.setState({ componentStack: errorInfo.componentStack ?? null });
    this.props.onError?.(error, {
      componentStack: errorInfo.componentStack,
      suppressed,
    });
  }

  handleRefresh = () => {
    window.location.reload();
  };

  render() {
    const { error, componentStack } = this.state;
    if (!error) return this.props.children;
    if (this.props.shouldSuppress?.(error)) return null;
    if (this.props.fallback) return this.props.fallback;

    return (
      <ErrorBoundaryFallback
        error={error}
        componentStack={componentStack}
        boundaryName={this.props.name}
        onRefresh={this.handleRefresh}
      />
    );
  }
}
