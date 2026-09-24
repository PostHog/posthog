import {
  SYSTEM_MAP_SERVICE,
  type SystemMapResult,
  type SystemMapScope,
  type SystemMapService,
  systemMapKey,
} from "@posthog/core/system-map/systemMapService";
import { useService } from "@posthog/di/react";
import { useAuthenticatedQuery } from "@posthog/ui/hooks/useAuthenticatedQuery";
import type { UseQueryResult } from "@tanstack/react-query";

export function useSavedSystemMap(
  scope: SystemMapScope | null,
): UseQueryResult<SystemMapResult | null, Error> {
  const service = useService<SystemMapService>(SYSTEM_MAP_SERVICE);
  return useAuthenticatedQuery(
    scope ? systemMapKey(scope) : ["system-map-v1", "unavailable"],
    (client) =>
      scope ? service.restore(client, scope) : Promise.resolve(null),
    {
      enabled: !!scope,
      staleTime: Infinity,
      retry: false,
    },
  );
}
