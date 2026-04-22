import z from 'zod'

/**
 * Shared predicate for deciding whether a flag-gated entry (tool, resource,
 * skill) should be exposed given a map of evaluated feature flags.
 *
 * Behavior:
 * - Entries without a `feature_flag` are always included.
 * - `enable` (default): entry included iff the flag is on.
 * - `disable`: entry included iff the flag is off.
 * - Missing flag key in `featureFlags` is treated as off — so `enable`
 *   entries are hidden by default until their flag evaluates true.
 * - Passing `undefined` for `featureFlags` has the same effect as an empty
 *   map: `enable` entries are hidden, `disable` entries are shown.
 */
export const FlagGatedSchema = z.object({
    /** PostHog feature flag key that gates this entry. */
    feature_flag: z.string().min(1).optional(),
    /** How the flag gates the entry: 'enable' (default) or 'disable'. */
    feature_flag_behavior: z.enum(['enable', 'disable']).optional(),
})

export type FlagBehavior = 'enable' | 'disable'

export type FlagGated = z.infer<typeof FlagGatedSchema>

export function shouldIncludeByFlag(entry: FlagGated, featureFlags?: Record<string, boolean>): boolean {
    if (!entry.feature_flag) {
        return true
    }
    const isOn = featureFlags ? featureFlags[entry.feature_flag] === true : false
    const behavior = entry.feature_flag_behavior ?? 'enable'
    return behavior === 'enable' ? isOn : !isOn
}
