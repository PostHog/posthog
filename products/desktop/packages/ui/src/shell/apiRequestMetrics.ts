import type {
  ApiRequestMetricRecorder,
  ApiRequestMetricRequest,
} from "@posthog/api-client/posthog-client";
import { getRouterOrNull } from "@posthog/ui/router/routerRef";
import { recordApiRequest } from "@posthog/ui/shell/posthogAnalyticsImpl";

/**
 * Wired into every renderer API client so a request is attributed to the route
 * it started on, not the one the user reached while it was still in flight.
 */
export function recordApiRequestStart({
  method,
  path,
}: ApiRequestMetricRequest): ApiRequestMetricRecorder {
  const route = getRouterOrNull()?.state.matches.at(-1)?.routeId ?? "unknown";

  return ({ durationMs, status, outcome }) => {
    recordApiRequest(durationMs, route, method, path, status, outcome);
  };
}
