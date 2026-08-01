export interface TaskListFilters {
  repository?: string;
  createdBy?: number;
  originProduct?: string;
  internal?: boolean;
}

export const taskKeys = {
  all: ["tasks"] as const,
  lists: () => [...taskKeys.all, "list"] as const,
  list: (filters?: TaskListFilters) => [...taskKeys.lists(), filters] as const,
  // Extract the filters object from a `list` query key. Keeps knowledge of the
  // key's shape (filters live in the last slot) here, next to `list`, instead
  // of letting consumers reach in by positional index.
  filtersOf: (queryKey: readonly unknown[]): TaskListFilters | undefined =>
    queryKey[queryKey.length - 1] as TaskListFilters | undefined,
  allSummaries: () => [...taskKeys.all, "summaries"] as const,
  summaries: (ids: string[]) =>
    [...taskKeys.allSummaries(), [...ids].sort()] as const,
  details: () => [...taskKeys.all, "detail"] as const,
  detail: (id: string) => [...taskKeys.details(), id] as const,
};
