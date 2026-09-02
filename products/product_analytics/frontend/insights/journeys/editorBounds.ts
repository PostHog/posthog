// Mirrors of PathsV2Filter's schema bounds, which the server enforces without clamping.
// editorBounds.test.ts pins each constant to the generated schema.json.

export const MAX_STEPS_BOUNDS = { min: 2, max: 20 }
export const MAX_ROWS_PER_STEP_BOUNDS = { min: 1, max: 10 }
export const MAX_STEP_SOURCES = 20
