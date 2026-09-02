/**
 * Sentinel the sparkline endpoint labels its collapsed tail with — the same value insights
 * breakdowns use. Duplicated rather than imported from `scenes/insights/utils` to keep that
 * module's graph out of the logs bundle, which is the convention that file already follows (it
 * carries its own "sync this with breakdowns.py" note). A test pins it to the Python constant.
 */
export const OTHER_BREAKDOWN_VALUE = '$$_posthog_breakdown_other_$$'

/**
 * Legend label for the collapsed bucket. Insights spells this "Other (i.e. all remaining values)",
 * which is too long for a sparkline legend, and deliberately dimension-neutral because the same
 * sentinel can stand in for services or severities.
 */
export const OTHER_BREAKDOWN_LABEL = 'Other'
