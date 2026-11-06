import { rescaleSampleSize } from 'scenes/experiments/RunningTimeCalculator/calculations'

import type {
    GoalScoutPlanAnchorApi,
    GoalScoutPlanApi,
    GoalScoutPlanInputApi,
} from 'products/signals/frontend/generated/api.schemas'

const MIN_DAYS = 2
const MAX_DAYS = 28
const LIMIT_DAYS = 365
const MIN_MDE = 0.1
const MAX_MDE = 100

export type PlanField = 'days' | 'mde' | 'audience'

export type PlanDraft = Record<PlanField, string>

export interface IdeaPlan {
    draft: PlanDraft
    input: GoalScoutPlanInputApi | null
    disabledReason: string | null
    audienceMissing: boolean
    tooLong: boolean
}

function parse(value: string, whole: boolean): number | null {
    const number = Number(value.trim().replace(',', '.'))
    if (!value.trim() || !Number.isFinite(number) || number <= 0) {
        return null
    }
    return whole ? Math.round(number) : number
}

export function formatMde(value: number): string {
    return String(Math.max(Math.round(value * 10) / 10, MIN_MDE))
}

export function initialDraft(plan: GoalScoutPlanApi): PlanDraft {
    return {
        days: plan.days ? String(plan.days) : '',
        mde: plan.mde ? formatMde(plan.mde) : '',
        audience: plan.audience ? String(plan.audience) : '',
    }
}

export function editDraft(
    draft: PlanDraft,
    anchor: GoalScoutPlanAnchorApi | null,
    field: PlanField,
    value: string
): PlanDraft {
    const next = { ...draft, [field]: value }
    const days = parse(next.days, true)
    const mde = parse(next.mde, false)
    const audience = parse(next.audience, true)
    if (!anchor || !audience) {
        return next
    }
    if (field === 'days' && days) {
        next.mde = formatMde(anchor.mde * Math.sqrt(anchor.sample_size / (days * audience)))
    }
    const sampleSize = field !== 'days' && mde ? rescaleSampleSize(anchor.sample_size, anchor.mde, mde) : null
    if (sampleSize !== null) {
        next.days = String(Math.max(Math.ceil(sampleSize / audience), MIN_DAYS))
    }
    return next
}

function disabledReason(days: number | null, mde: number | null, audience: number | null): string | null {
    if (!audience) {
        return 'Enter how many people a day see this change.'
    }
    if (!days || days < MIN_DAYS) {
        return `Run for at least ${MIN_DAYS} days.`
    }
    if (days > LIMIT_DAYS) {
        return `Run for at most ${LIMIT_DAYS} days. Look for a larger change or more people.`
    }
    if (!mde || mde < MIN_MDE) {
        return `Look for a change of at least ${MIN_MDE}%.`
    }
    if (mde > MAX_MDE) {
        return 'This run can only find a change over 100%. Run longer or add more people.'
    }
    return null
}

export function ideaPlan(draft: PlanDraft): IdeaPlan {
    const days = parse(draft.days, true)
    const mde = parse(draft.mde, false)
    const audience = parse(draft.audience, true)
    const reason = disabledReason(days, mde, audience)
    return {
        draft,
        input: reason || !days || !mde || !audience ? null : { days, mde, audience },
        disabledReason: reason,
        audienceMissing: !audience,
        tooLong: !!days && days > MAX_DAYS,
    }
}

export function stepValue(value: string, field: PlanField, direction: 1 | -1): string {
    const step = field === 'mde' ? 0.1 : 1
    const current = parse(value, field !== 'mde') ?? 0
    return String(Math.max(Math.round((current + step * direction) * 10) / 10, step))
}
