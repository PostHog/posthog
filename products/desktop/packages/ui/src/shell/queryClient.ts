import type { QueryClient } from "@tanstack/react-query";

export type ImperativeQueryClient = QueryClient;

export const IMPERATIVE_QUERY_CLIENT = Symbol.for(
  "posthog.ui.ImperativeQueryClient",
);
