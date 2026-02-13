// AUTO-GENERATED from products/error_tracking/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import {
    ErrorTrackingIssuesListQueryParams,
    ErrorTrackingIssuesPartialUpdateBody,
    ErrorTrackingIssuesPartialUpdateParams,
    ErrorTrackingIssuesRetrieveParams,
} from '@/generated/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const ErrorTrackingIssuesListSchema = ErrorTrackingIssuesListQueryParams

const errorTrackingIssuesList = (): ToolBase<typeof ErrorTrackingIssuesListSchema> => ({
    name: 'error-tracking-issues-list',
    schema: ErrorTrackingIssuesListSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesListSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'GET',
            path: `/api/environments/${projectId}/error_tracking/issues/`,
            query: {
                limit: params.limit,
                offset: params.offset,
            },
        })
        return result
    },
})

const ErrorTrackingIssuesRetrieveSchema = ErrorTrackingIssuesRetrieveParams.omit({ project_id: true })

const errorTrackingIssuesRetrieve = (): ToolBase<typeof ErrorTrackingIssuesRetrieveSchema> => ({
    name: 'error-tracking-issues-retrieve',
    schema: ErrorTrackingIssuesRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesRetrieveSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const result = await context.api.request({
            method: 'GET',
            path: `/api/environments/${projectId}/error_tracking/issues/${params.id}/`,
        })
        return result
    },
})

const ErrorTrackingIssuesPartialUpdateSchema = ErrorTrackingIssuesPartialUpdateParams.omit({ project_id: true }).merge(
    ErrorTrackingIssuesPartialUpdateBody
)

const errorTrackingIssuesPartialUpdate = (): ToolBase<typeof ErrorTrackingIssuesPartialUpdateSchema> => ({
    name: 'error-tracking-issues-partial-update',
    schema: ErrorTrackingIssuesPartialUpdateSchema,
    handler: async (context: Context, params: z.infer<typeof ErrorTrackingIssuesPartialUpdateSchema>) => {
        const projectId = await context.stateManager.getProjectId()
        const body: Record<string, unknown> = {}
        if (params.status !== undefined) {
            body['status'] = params.status
        }
        if (params.name !== undefined) {
            body['name'] = params.name
        }
        if (params.description !== undefined) {
            body['description'] = params.description
        }
        if (params.first_seen !== undefined) {
            body['first_seen'] = params.first_seen
        }
        if (params.assignee !== undefined) {
            body['assignee'] = params.assignee
        }
        if (params.external_issues !== undefined) {
            body['external_issues'] = params.external_issues
        }
        const result = await context.api.request({
            method: 'PATCH',
            path: `/api/environments/${projectId}/error_tracking/issues/${params.id}/`,
            body,
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'error-tracking-issues-list': errorTrackingIssuesList,
    'error-tracking-issues-retrieve': errorTrackingIssuesRetrieve,
    'error-tracking-issues-partial-update': errorTrackingIssuesPartialUpdate,
}
