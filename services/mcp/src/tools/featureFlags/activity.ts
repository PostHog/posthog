import type { z } from 'zod'

import { FeatureFlagActivityGetSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'

const schema = FeatureFlagActivityGetSchema

type Params = z.infer<typeof schema>

interface FormattedActivity {
    timestamp: string
    user: {
        email: string
        name: string
    } | null
    action: string
    flagId: string | null
    changes: Array<{
        field: string
        action: string
        before?: unknown
        after?: unknown
    }>
    url: string
}

export const activityHandler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const activityResult = await context.api.activityLog({ projectId }).list({
        scope: 'FeatureFlag',
        itemId: params.flagId,
        startDate: params.startDate,
        endDate: params.endDate,
    })

    if (!activityResult.success) {
        throw new Error(`Failed to get feature flag activity: ${activityResult.error.message}`)
    }

    const baseUrl = context.api.getProjectBaseUrl(projectId)

    // Format the activities for better readability
    const formattedActivities: FormattedActivity[] = activityResult.data.results
        .slice(0, params.limit ?? 50)
        .map((entry: (typeof activityResult.data.results)[number]) => {
            const changes: FormattedActivity['changes'] = []

            // Parse the detail field to extract changes
            if (entry.detail) {
                const detail = entry.detail as Record<string, unknown>

                // Handle 'changes' array format
                if (Array.isArray(detail.changes)) {
                    for (const change of detail.changes) {
                        const c = change as Record<string, unknown>
                        changes.push({
                            field: String(c.field ?? 'unknown'),
                            action: String(c.action ?? 'changed'),
                            before: c.before,
                            after: c.after,
                        })
                    }
                }

                // Handle direct field changes
                if (detail.name !== undefined) {
                    changes.push({ field: 'name', action: 'set', after: detail.name })
                }
                if (detail.short_id !== undefined) {
                    changes.push({ field: 'short_id', action: 'set', after: detail.short_id })
                }
            }

            return {
                timestamp: entry.created_at,
                user: entry.user
                    ? {
                          email: entry.user.email,
                          name:
                              [entry.user.first_name, entry.user.last_name].filter(Boolean).join(' ') ||
                              entry.user.email,
                      }
                    : null,
                action: entry.activity,
                flagId: entry.item_id,
                changes,
                url: `${baseUrl}/activity/explore`,
            }
        })

    return {
        activities: formattedActivities,
        totalCount: activityResult.data.results.length,
        hasMore: !!activityResult.data.next,
    }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'feature-flag-activity-get',
    schema,
    handler: activityHandler,
})

export default tool
