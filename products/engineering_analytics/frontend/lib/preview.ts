// Hub preview standard. The repo hub is a landing page: each table shows a short, scannable slice and
// routes to its dedicated full view for the rest — it never restates the whole table. One standard so
// every preview table starts the same length and grows by the same step on "Show more".
// Typed as number (not the literal) so the reducer that grows the count keeps a widened number state.
export const HUB_PREVIEW_ROWS: number = 5 // rows shown before any expansion
export const HUB_PREVIEW_STEP: number = 5 // rows revealed per "Show more"
export const HUB_PREVIEW_MAX: number = 15 // ceiling on the hub — past this, "View all" is the only way deeper
