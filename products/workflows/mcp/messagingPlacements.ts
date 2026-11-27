import { z } from 'zod'

export type MessagingArea = 'flags' | 'cohorts' | 'insights' | 'replay' | 'mcp'

export const messagingCtaCopySchema = z.object({
    label: z.string().trim().min(1).max(60),
    description: z.string().max(200).optional(),
})

export type MessagingCtaCopy = z.infer<typeof messagingCtaCopySchema>

export interface MessagingPlacement {
    readonly key: `${MessagingArea}.${string}`
    readonly area: MessagingArea
    readonly variant: string
    readonly defaultCopy: MessagingCtaCopy
}

export const areaFlag = (area: MessagingArea): string => `xpm-${area}-placement`

export const PLACEMENTS = [
    {
        key: 'mcp.after_cohorts_create',
        area: 'mcp',
        variant: 'after_cohorts_create',
        defaultCopy: {
            label: 'Email the people in this cohort',
            description: 'The user can send this cohort an email. They review and launch it in the broadcast editor.',
        },
    },
] as const satisfies readonly MessagingPlacement[]

export type MessagingPlacementKey = (typeof PLACEMENTS)[number]['key']

export interface FlagReader {
    value(flag: string): boolean | string | undefined
    payload(flag: string): unknown
}

export type PlacementState =
    | { active: true; placement: MessagingPlacement; copy: MessagingCtaCopy }
    | { active: false; reason: 'holdout' | 'not_this_variant' }

const EXPERIMENT_HOLDOUT_VARIANT_PREFIX = 'holdout-'

function placementFor(key: MessagingPlacementKey): MessagingPlacement {
    const placement = PLACEMENTS.find((candidate) => candidate.key === key)
    if (!placement) {
        throw new Error(`Unknown messaging placement: ${key}`)
    }
    return placement
}

export function placementState(key: MessagingPlacementKey, flags: FlagReader): PlacementState {
    const placement = placementFor(key)
    const flag = areaFlag(placement.area)
    const value = flags.value(flag)
    if (typeof value === 'string' && value.startsWith(EXPERIMENT_HOLDOUT_VARIANT_PREFIX)) {
        return { active: false, reason: 'holdout' }
    }
    if (value !== placement.variant) {
        return { active: false, reason: 'not_this_variant' }
    }
    const payloadCopy = messagingCtaCopySchema.safeParse(flags.payload(flag))
    return { active: true, placement, copy: payloadCopy.success ? payloadCopy.data : placement.defaultCopy }
}
