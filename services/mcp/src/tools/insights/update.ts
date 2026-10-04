/**
 * Hand-written override of generated `insight-update`. It refuses a call with no
 * field to change, and it checks that the saved insight holds the requested
 * values before it reports success. Everything else delegates to the codegen factory.
 *
 * The schema drops keys it does not declare, so a misnamed or nested field reaches
 * the handler as an empty patch. The API accepts an empty PATCH, saves the row, and
 * returns it with only `updated_at` changed, which reads as a success.
 *
 * Title, description, and scopes still resolve from the generated
 * `insight-update` entry, not from this file.
 */
import type { Schemas } from '@/api/generated'
import { ToolInputValidationError } from '@/lib/errors'
import { GENERATED_TOOLS } from '@/tools/generated/product_analytics'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const UPDATABLE_INSIGHT_FIELDS = ['name', 'description', 'query', 'tags', 'favorited', 'dashboards'] as const

type UpdateParams = {
    id: number | string
    name?: string | null
    description?: string | null
    tags?: unknown[]
    favorited?: boolean
    dashboards?: number[]
    [key: string]: unknown
}

// The API trims text fields and stores tags trimmed, lowercased, and deduplicated.
const normalizeText = (value: unknown): string => (typeof value === 'string' ? value.trim() : '')
const normalizeTags = (tags: unknown[]): string[] =>
    [...new Set(tags.map((tag) => normalizeText(tag).toLowerCase()))].sort()
const sortedIds = (ids: number[]): number[] => [...new Set(ids)].sort((a, b) => a - b)

// The API can omit the deprecated `dashboards` field, but it always returns `dashboard_tiles`.
function savedDashboardIds(saved: Schemas.Insight): number[] | undefined {
    if (Array.isArray(saved.dashboard_tiles)) {
        return saved.dashboard_tiles.filter((tile) => !tile.deleted).map((tile) => tile.dashboard_id)
    }
    return Array.isArray(saved.dashboards) ? saved.dashboards : undefined
}

/** Names the requested fields that the saved insight does not hold. `query` is not
 *  compared, because the API normalizes the query it stores. */
function unpersistedInsightFields(params: UpdateParams, saved: Schemas.Insight): string[] {
    const mismatched: string[] = []
    if (params.name !== undefined && normalizeText(params.name) !== normalizeText(saved.name)) {
        mismatched.push('name')
    }
    if (params.description !== undefined && normalizeText(params.description) !== normalizeText(saved.description)) {
        mismatched.push('description')
    }
    if (params.favorited !== undefined && params.favorited !== saved.favorited) {
        mismatched.push('favorited')
    }
    if (
        params.tags !== undefined &&
        Array.isArray(saved.tags) &&
        JSON.stringify(normalizeTags(params.tags)) !== JSON.stringify(normalizeTags(saved.tags))
    ) {
        mismatched.push('tags')
    }
    const dashboardIds = savedDashboardIds(saved)
    if (
        params.dashboards !== undefined &&
        dashboardIds !== undefined &&
        JSON.stringify(sortedIds(params.dashboards)) !== JSON.stringify(sortedIds(dashboardIds))
    ) {
        mismatched.push('dashboards')
    }
    return mismatched
}

export default function updateInsightVerifyingPersistence(): ToolBase<ZodObjectAny> {
    const generated = GENERATED_TOOLS['insight-update']!()

    return {
        // Spreading the generated tool carries over any field codegen adds later.
        ...generated,
        handler: async (context: Context, params: UpdateParams) => {
            if (!UPDATABLE_INSIGHT_FIELDS.some((field) => params[field] !== undefined)) {
                throw new ToolInputValidationError(
                    `insight-update received no field to change, so nothing was saved. Pass at least one of ${UPDATABLE_INSIGHT_FIELDS.join(', ')} at the top level, next to "id". The tool ignores any other key.`,
                    { inputKeys: Object.keys(params) }
                )
            }

            const result = await generated.handler(context, params)

            const mismatched = unpersistedInsightFields(params, result as Schemas.Insight)
            if (mismatched.length > 0) {
                throw new Error(
                    `insight-update sent the change, but the saved insight does not hold the requested value for: ${mismatched.join(', ')}. Call insight-get to read the current state before you retry.`
                )
            }
            return result
        },
    }
}
