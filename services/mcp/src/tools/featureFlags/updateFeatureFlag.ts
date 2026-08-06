/**
 * Hand-written override of generated `update-feature-flag`.
 *
 * Same surface as codegen, but when `filters` is provided we fetch the current
 * flag and merge group-targeting fields so agents cannot silently convert
 * group-targeted flags to person targeting (PostHog/posthog#46501).
 */
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import {
    FeatureFlagsPartialUpdateBody,
    FeatureFlagsPartialUpdateParams,
} from '@/generated/feature_flags/api'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'
import { castStringToInt } from '@/tools/cast-helpers'

import { preserveGroupTargetingFilters, type FlagFilters } from './preserveGroupTargeting'

const UpdateFeatureFlagSchema = FeatureFlagsPartialUpdateParams.omit({ project_id: true })
    .extend(FeatureFlagsPartialUpdateBody.shape)
    .extend({
        id: z.preprocess(castStringToInt, FeatureFlagsPartialUpdateParams.shape['id']),
        is_remote_configuration: FeatureFlagsPartialUpdateBody.shape['is_remote_configuration'].describe(
            'Whether this flag delivers a payload instead of gating a feature (Remote Config mode). When true, set the delivered payload through the `filters` param under `filters.payloads.true` as a JSON-encoded string. There is no dedicated payload parameter.'
        ),
        ensure_experience_continuity: FeatureFlagsPartialUpdateBody.shape['ensure_experience_continuity'].describe(
            'Whether to persist the flag\'s value for a user across the anonymous-to-identified transition (the "persist across authentication steps" option in the UI). Keeps a user\'s evaluated value stable once they log in. Incompatible with `device_id` bucketing.'
        ),
        evaluation_runtime: FeatureFlagsPartialUpdateBody.shape['evaluation_runtime'].describe(
            'Where this flag is allowed to evaluate — `server` (server-side SDKs only), `client` (client-side SDKs only), or `all` (both). Defaults to `all`.'
        ),
        bucketing_identifier: FeatureFlagsPartialUpdateBody.shape['bucketing_identifier'].describe(
            'Identifier used to bucket users into rollout percentages and variants — `distinct_id` (user ID, the default) or `device_id`. Using `device_id` is incompatible with `ensure_experience_continuity=true`.'
        ),
        filters: FeatureFlagsPartialUpdateBody.shape['filters'].describe(
            'Release conditions for the flag. ' +
                'For **group-targeted** flags (e.g. workspaces): set `filters.aggregation_group_type_index` to the group type index, ' +
                'and on each property set `type: "group"` plus `group_type_index`. ' +
                'For person targeting use `type: "person"`. ' +
                'If you omit type / group_type_index / aggregation_group_type_index on an update, the server merges them from the existing flag so group targeting is not silently lost. ' +
                'Always pass the full intended `groups` array (partial property patches replace the whole filters object at the API layer).'
        ),
    })

const updateFeatureFlag = (): ToolBase<typeof UpdateFeatureFlagSchema, WithPostHogUrl<Schemas.FeatureFlag>> => ({
    name: 'update-feature-flag',
    schema: UpdateFeatureFlagSchema,
    handler: async (context: Context, params: z.infer<typeof UpdateFeatureFlagSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}

        if (params.key !== undefined) {
            body['key'] = params.key
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }

        if (params.filters !== undefined) {
            // Fetch current definition so we can preserve group targeting fields
            // the agent may have omitted while rewriting conditions.
            let existingFilters: FlagFilters | undefined
            try {
                const existing = await context.api.request<Schemas.FeatureFlag>({
                    method: 'GET',
                    path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/`,
                })
                existingFilters = (existing?.filters ?? undefined) as FlagFilters | undefined
            } catch {
                // If fetch fails, still apply filters as provided rather than blocking the update.
                existingFilters = undefined
            }
            body['filters'] = preserveGroupTargetingFilters(existingFilters, params.filters as FlagFilters)
        }

        if (params.active !== undefined) {
            body['active'] = params.active
        }
        if (params.archived !== undefined) {
            body['archived'] = params.archived
        }
        if (params.tags !== undefined) {
            body['tags'] = params.tags
        }
        if (params.evaluation_contexts !== undefined) {
            body['evaluation_contexts'] = params.evaluation_contexts
        }
        if (params.is_remote_configuration !== undefined) {
            body['is_remote_configuration'] = params.is_remote_configuration
        }
        if (params.ensure_experience_continuity !== undefined) {
            body['ensure_experience_continuity'] = params.ensure_experience_continuity
        }
        if (params.evaluation_runtime !== undefined) {
            body['evaluation_runtime'] = params.evaluation_runtime
        }
        if (params.bucketing_identifier !== undefined) {
            body['bucketing_identifier'] = params.bucketing_identifier
        }

        const result = await context.api.request<Schemas.FeatureFlag>({
            method: 'PATCH',
            path: `/api/projects/${encodeURIComponent(String(projectId))}/feature_flags/${encodeURIComponent(String(params.id))}/`,
            body,
        })
        return await withPostHogUrl(context, result, `/feature_flags/${result.id}`)
    },
})

export default updateFeatureFlag
