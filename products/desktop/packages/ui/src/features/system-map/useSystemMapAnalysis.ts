import {
  SYSTEM_MAP_SERVICE,
  type SystemMapRequest,
  type SystemMapService,
  systemMapKey,
} from "@posthog/core/system-map/systemMapService";
import { useService } from "@posthog/di/react";
import { ANALYTICS_EVENTS } from "@posthog/shared/analytics-events";
import { useAuthenticatedMutation } from "@posthog/ui/hooks/useAuthenticatedMutation";
import { captureException, track } from "@posthog/ui/shell/analytics";
import { useQueryClient } from "@tanstack/react-query";

export function useSystemMapAnalysis() {
  const service = useService<SystemMapService>(SYSTEM_MAP_SERVICE);
  const queryClient = useQueryClient();
  return useAuthenticatedMutation(
    (client, request: SystemMapRequest) => service.analyze(client, request),
    {
      retry: false,
      onMutate: () => track(ANALYTICS_EVENTS.SYSTEM_MAP_ANALYSIS_STARTED),
      onSuccess: (result, request) => {
        queryClient.setQueryData(systemMapKey(request), result);
        track(ANALYTICS_EVENTS.SYSTEM_MAP_ANALYSIS_COMPLETED, {
          area_count: result.map.areas.length,
          component_count: result.map.areas.reduce(
            (total, area) => total + area.components.length,
            0,
          ),
          relationship_count: result.map.relationships.length,
        });
      },
      onError: (_error, request) => {
        track(ANALYTICS_EVENTS.SYSTEM_MAP_ANALYSIS_FAILED, {
          reason: request.signal.aborted ? "cancelled" : "failed",
        });
        if (!request.signal.aborted)
          captureException(new Error("System map analysis failed"), {
            scope: "system-map",
          });
      },
    },
  );
}
