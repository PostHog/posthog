import z from 'zod'

/**
 * Shared flag-gating schema for tools, resources, and skills.
 *
 * - No `feature_flag`: always included.
 * - `enable` (default): included iff the flag is on.
 * - `disable`: included iff the flag is off.
 * - Missing or `undefined` flags map are treated as off.
 */
export const FlagGatedSchema = z.object({
    feature_flag: z
        .string()
        .refine((v) => v.trim().length > 0, { message: 'feature_flag must be a non-empty string' })
        .optional(),
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
