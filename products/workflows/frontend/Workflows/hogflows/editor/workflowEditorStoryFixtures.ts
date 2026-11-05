import { mswDecorator } from '~/mocks/browser'

import { NEW_WORKFLOW } from '../../workflowLogic'
import type { HogFlow } from '../types'

export function createWorkflowEditorStoryDecorator(
    workflowsById: Record<string, HogFlow>
): ReturnType<typeof mswDecorator> {
    return mswDecorator({
        get: {
            '/api/projects/:team_id/hog_flow_templates/': { count: 0, results: [] },
            // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
            '/api/environments/:team_id/hog_flows/:id/': ({ params }) => [200, workflowsById[String(params.id)]],
            // nosemgrep: no-environments-api-urls-frontend -- api.messaging has not migrated to generated project routes.
            '/api/environments/:team_id/messaging_categories': { count: 0, results: [] },
            '/api/projects/:team_id/workflow_imports/for_workflow/': [204],
        },
        patch: {
            // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
            '/api/environments/:team_id/hog_flows/:id/': async ({ request, params }) => [
                200,
                {
                    ...workflowsById[String(params.id)],
                    ...((await request.json()) as Partial<HogFlow>),
                    updated_at: '2026-09-04T12:01:00.000Z',
                },
            ],
        },
        post: {
            // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
            '/api/environments/:team_id/hog_flows/': async ({ request }) => [
                201,
                {
                    ...NEW_WORKFLOW,
                    ...((await request.json()) as Partial<HogFlow>),
                    id: 'storybook-new-workflow',
                    team_id: 1,
                    created_at: '2026-09-04T12:01:00.000Z',
                    updated_at: '2026-09-04T12:01:00.000Z',
                },
            ],
            // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
            '/api/environments/:team_id/hog_flows/user_blast_radius/': {
                affected: 240,
                total: 1200,
                limit: 100000,
                dedupe_key: null,
                confirm_token: 'storybook-confirm-token',
            },
        },
    })
}
