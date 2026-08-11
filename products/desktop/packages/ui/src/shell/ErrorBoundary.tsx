import {
  type ErrorBoundaryProps,
  ErrorBoundary as UiErrorBoundary,
} from "@posthog/ui/primitives/ErrorBoundary";
import { captureException } from "@posthog/ui/shell/analytics";
import { logger } from "@posthog/ui/shell/logger";

const log = logger.scope("error-boundary");

export type { ErrorBoundaryProps };

/**
 * Desktop wrapper around the host-agnostic ErrorBoundary primitive. Supplies
 * the app's telemetry/logging via onError so the primitive stays portable.
 */
export function ErrorBoundary(props: ErrorBoundaryProps) {
  return (
    <UiErrorBoundary
      {...props}
      onError={(error, info) => {
        if (info.suppressed) {
          log.warn("Suppressed error in boundary", {
            name: props.name,
            error: error.message,
          });
        } else {
          log.error("Error caught by boundary", {
            name: props.name,
            error: error.message,
            stack: error.stack,
            componentStack: info.componentStack,
          });
          captureException(error, {
            $exception_component_stack: info.componentStack,
            boundary_name: props.name,
            source: "error-boundary",
          });
        }
        props.onError?.(error, info);
      }}
    />
  );
}
