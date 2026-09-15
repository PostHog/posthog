import type { HogFlow } from './hogflows/types'

const MINUTES_PER_DAY = 1440
// The worker shortens a legacy window_minutes to this ceiling before it measures anything, and the API
// only accepts a larger value on a workflow that already holds it. Mirrors MAX_LEGACY_WINDOW_MINUTES in
// products/workflows/backend/api/hog_flow.py.
const MAX_LEGACY_WINDOW_MINUTES = 90 * MINUTES_PER_DAY

function durationString(minutes: number): string {
    if (minutes % MINUTES_PER_DAY === 0) {
        return `${minutes / MINUTES_PER_DAY}d`
    }
    if (minutes % 60 === 0) {
        return `${minutes / 60}h`
    }
    return `${minutes}m`
}

type Conversion = NonNullable<HogFlow['conversion']>

// A copy posts as a create, so the API validates the stored conversion as if the user had just typed it.
// A workflow written before the ceiling can hold a window_minutes above it, which no create may carry and
// the builder cannot edit, so the copy is respelled as the duration-string window the API takes now. The
// value is clamped the same way the worker clamps it, so the copy measures the period the original does.
function conversionWithDurationWindow(conversion: Conversion): Conversion {
    const minutes = conversion.window_minutes
    if (conversion.window || typeof minutes !== 'number' || !Number.isFinite(minutes) || minutes <= 0) {
        return conversion
    }
    const { window_minutes, ...rest } = conversion
    return { ...rest, window: durationString(Math.min(minutes, MAX_LEGACY_WINDOW_MINUTES)) }
}

export function prepareWorkflowDuplicate(workflow: HogFlow): Partial<HogFlow> {
    const duplicate: Partial<HogFlow> & { origin_product?: unknown } = {
        ...workflow,
        name: `${workflow.name} (copy)`,
        status: 'draft',
    }

    delete duplicate.id
    delete duplicate.team_id
    delete duplicate.created_at
    delete duplicate.updated_at
    delete duplicate.origin_product

    if (duplicate.conversion) {
        duplicate.conversion = conversionWithDurationWindow(duplicate.conversion)
    }

    return duplicate
}
