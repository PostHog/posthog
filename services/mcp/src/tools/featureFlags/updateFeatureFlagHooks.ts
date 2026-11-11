/**
 * Hooks for the generated `update-feature-flag` tool. They intercept only `filters`, to
 * preserve group targeting (PostHog/posthog#46501) and to explain a rejected property type or
 * group type, and leave everything else to the generated handler. Re-sync is needed if the
 * `filters` param shape changes, if the API changes the `groups[i].properties[j].type: ` prefix
 * of its property type rejection, or if it changes the code or the `groups[i].properties[j]: `
 * prefix of its group type mismatch rejection.
 * The merge removes each `condition_id` before the PATCH, because the API does not store it.
 * afterResponse adds a `condition_id` to each condition in the returned flag.
 */
import type { Schemas } from '@/api/generated'
import { PostHogValidationError } from '@/lib/errors'
import type { ToolHooks } from '@/tools/tool-hooks'
import type { Context } from '@/tools/types'

import conditionIdHooks from './conditionIdHooks'
import { preserveGroupTargetingFilters, type FlagFilters } from './preserveGroupTargeting'

type UpdateParams = {
    id: number | string
    filters?: FlagFilters | null
    [key: string]: unknown
}

// The `.type` form matches both the API's serde guard ("invalid property type") and its structural
// tier ("This field is required.", "... is not a valid choice."), which differ only after the path.
const PROPERTY_REJECTION = /^(groups\[(\d+)\]\.properties\[(\d+)\])(\.type)?: /

const GROUP_TYPE_MISMATCH = 'cross_field.group_property_type_index_mismatch'

async function beforeRequest<T extends UpdateParams>(context: Context, params: T): Promise<T> {
    if (params.filters === undefined) {
        return params
    }

    // No try/catch: a failed GET must abort before the PATCH. PATCHing raw
    // filters without the merge is what silently demotes group flags.
    const projectId = await context.stateManager.getProjectId()
    const existing = await context.api.request<Schemas.FeatureFlag>({
        method: 'GET',
        path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/`,
    })
    const existingFilters = (existing?.filters ?? undefined) as FlagFilters | undefined
    const mergedFilters = preserveGroupTargetingFilters(existingFilters, params.filters)

    return { ...params, filters: mergedFilters }
}

// The API reports a rejected property type or group type by path only. This adds the key from the
// sent filters and the recovery step, whether `beforeRequest` restored the value or the agent sent
// it. The rewrite keeps the PostHogValidationError class for two reasons. `handleToolError` returns
// that class's message to the agent. Telemetry records only its code and attr, so the property
// key stays out of analytics.
function onError(_context: Context, params: UpdateParams, error: unknown): never {
    if (!(error instanceof PostHogValidationError) || error.method !== 'PATCH' || error.attr !== 'filters') {
        throw error
    }
    const match = PROPERTY_REJECTION.exec(error.detail)
    if (!match) {
        throw error
    }
    const [, path, groupIndex, propertyIndex, typeField] = match
    const recoveryStep = typeField
        ? propertyTypeRecoveryStep
        : error.code === GROUP_TYPE_MISMATCH
          ? groupTypeRecoveryStep
          : undefined
    const key: unknown = params.filters?.groups?.[Number(groupIndex)]?.properties?.[Number(propertyIndex)]?.key
    if (!recoveryStep || typeof key !== 'string') {
        throw error
    }
    throw new PostHogValidationError({
        ...error,
        detail: `${error.detail}\n\n${recoveryStep(`filters.${path}`, key)}`,
    })
}

function propertyTypeRecoveryStep(path: string, key: string): string {
    const quotedKey = JSON.stringify(key)
    return (
        `The property at ${path} (key ${quotedKey}) has a missing or invalid \`type\`. Read the flag. ` +
        `If the flag already filters on ${quotedKey}, copy that filter's \`type\`, and its \`group_type_index\` ` +
        `for a group property, from the stored condition you mean. ` +
        `If that stored filter has no \`type\` either, ask the user which type to use. ` +
        `Don't guess \`person\`: the API accepts it, and the condition then filters on a person property named ${quotedKey}. ` +
        `If the flag doesn't filter on ${quotedKey} yet, set the \`type\` you mean, plus \`group_type_index\` for a group property.`
    )
}

function groupTypeRecoveryStep(path: string, key: string): string {
    return (
        `The group property at ${path} (key ${JSON.stringify(key)}) is on a different group type than its condition aggregates on. ` +
        `If the flag you read already has it this way, the flag checks this property on the property's own group type. ` +
        `Changing the property's \`group_type_index\` or the condition's \`aggregation_group_type_index\` to make them match ` +
        `changes which group the flag checks, so don't pick one yourself. ` +
        `Ask the user which group type the condition should target, then set both to that group type's index.`
    )
}

export default {
    ...conditionIdHooks,
    beforeRequest,
    onError,
} satisfies ToolHooks<UpdateParams>
