/**
 * Constants for text view display and behavior
 */

/** Timeout for text representation API requests in milliseconds */
export const TEXT_REPR_API_TIMEOUT_MS = 10000 // 10 seconds

/** Delay before triggering fallback to standard view in milliseconds */
export const FALLBACK_DELAY_MS = 1500 // 1.5 seconds

/** Number of tools to show before hiding the rest behind an expand button */
export const VISIBLE_TOOLS_COUNT = 5

/**
 * Max character length for UI text representation.
 *
 * Much larger than the LLM context limit (3M) since browsers can handle more.
 * With include_markers=true, expandable content is base64-encoded and hidden
 * until clicked, so the initial DOM render is compact regardless of this limit.
 *
 * Based on trace size distribution:
 * - 95% of traces are under 10M chars
 * - 98% of traces are under 20M chars
 * - A few extreme outliers can reach 100M+ chars
 *
 * 20M handles the vast majority without truncation while still protecting
 * against browser issues from extreme outliers.
 */
export const UI_TEXT_REPR_MAX_LENGTH = 20_000_000
