/**
 * Maps the `variant_notes` and `variant_screenshot_media_ids` tool inputs onto the experiment's
 * `parameters`, and summarizes them for list responses. The API stores both keys in `parameters`,
 * next to the deprecated flag-config keys that the tools do not expose.
 */

const VARIANT_DETAIL_KEYS = ['variant_notes', 'variant_screenshot_media_ids'] as const

// Reads project the linked flag's config into `parameters`. Writing these keys back sends flag
// config through the deprecated surface, so a merged `parameters` must not carry them.
const PROJECTED_FLAG_CONFIG_KEYS = new Set([
    'feature_flag_variants',
    'rollout_percentage',
    'aggregation_group_type_index',
    'feature_flag_payloads',
    'ensure_experience_continuity',
])

type ExperimentParameters = Record<string, unknown>

export type VariantDetailParams = {
    variant_notes?: Record<string, string> | undefined
    variant_screenshot_media_ids?: Record<string, string[]> | undefined
    [key: string]: unknown
}

export function hasVariantDetails(params: VariantDetailParams): boolean {
    return VARIANT_DETAIL_KEYS.some((key) => params[key] !== undefined)
}

/**
 * Moves the variant detail inputs from the top level of the body into `parameters`. Each input
 * changes only the variants it names, so the result keeps the other variants of `existing`.
 */
export function withVariantDetailsInParameters(
    body: Record<string, unknown>,
    params: VariantDetailParams,
    existing: ExperimentParameters | null | undefined
): Record<string, unknown> {
    const { variant_notes: _notes, variant_screenshot_media_ids: _screenshots, ...rest } = body
    if (!hasVariantDetails(params)) {
        return rest
    }
    const parameters: ExperimentParameters = Object.fromEntries(
        Object.entries(existing ?? {}).filter(([key]) => !PROJECTED_FLAG_CONFIG_KEYS.has(key))
    )
    for (const key of VARIANT_DETAIL_KEYS) {
        const input = params[key]
        if (input !== undefined) {
            parameters[key] = { ...asRecord(parameters[key]), ...input }
        }
    }
    return { ...rest, parameters }
}

/** Replaces the variant detail maps of a list row with the keys of the variants that have them. */
export function summarizeVariantDetails<T extends { parameters?: unknown }>(
    row: T
): Omit<T, 'parameters'> & { variants_with_notes: string[]; variants_with_screenshots: string[] } {
    const { parameters, ...rest } = row
    const details = asRecord(parameters)
    return {
        ...rest,
        variants_with_notes: variantKeysWhere(details.variant_notes, (note) => typeof note === 'string' && note !== ''),
        variants_with_screenshots: variantKeysWhere(
            details.variant_screenshot_media_ids,
            (ids) =>
                (typeof ids === 'string' && ids !== '') ||
                (Array.isArray(ids) && ids.some((id) => typeof id === 'string' && id !== ''))
        ),
    }
}

/** Adds `variant_screenshot_urls`, the public image URLs of `variant_screenshot_media_ids`, keyed by variant key. */
export function withVariantScreenshotUrls<T extends { parameters?: unknown }>(
    experiment: T,
    publicBaseUrl: string
): T & { variant_screenshot_urls: Record<string, string[]> } {
    const mediaIds = asRecord(asRecord(experiment.parameters).variant_screenshot_media_ids)
    const urls = Object.fromEntries(
        Object.entries(mediaIds).map(([variantKey, ids]) => [
            variantKey,
            (Array.isArray(ids) ? ids : [ids])
                .filter((id): id is string => typeof id === 'string' && id !== '')
                .map((id) => `${publicBaseUrl}/uploaded_media/${encodeURIComponent(id)}`),
        ])
    )
    return { ...experiment, variant_screenshot_urls: urls }
}

function variantKeysWhere(value: unknown, predicate: (entry: unknown) => boolean): string[] {
    return Object.entries(asRecord(value))
        .filter(([, entry]) => predicate(entry))
        .map(([key]) => key)
}

function asRecord(value: unknown): Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
        ? (value as Record<string, unknown>)
        : {}
}
