export interface NewTaskSearch {
  mode?: "autoresearch";
}

/** Keeps only the new-task search values the composer understands. */
export function validateNewTaskSearch(
  search: Record<string, unknown>,
): NewTaskSearch {
  return search.mode === "autoresearch" ? { mode: "autoresearch" } : {};
}
