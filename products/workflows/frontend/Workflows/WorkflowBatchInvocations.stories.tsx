import type { Meta, StoryFn } from '@storybook/react'
import { BindLogic } from 'kea'

import { mswDecorator } from '~/mocks/browser'

import type { HogFlow } from './hogflows/types'
import { WorkflowBatchInvocations } from './WorkflowBatchInvocations'
import { NEW_WORKFLOW, WorkflowLogicProps, workflowLogic } from './workflowLogic'

const LOGIC_PROPS: WorkflowLogicProps = { id: 'storybook-batch-workflow' }

const BATCH_WORKFLOW: HogFlow = {
    ...NEW_WORKFLOW,
    id: LOGIC_PROPS.id!,
    name: 'Product update announcement',
    trigger: { type: 'batch', filters: { properties: [] } },
    actions: [
        {
            id: 'trigger',
            type: 'trigger',
            name: 'Batch audience',
            description: 'Send to everyone matching the filters.',
            config: { type: 'batch', filters: { properties: [] } },
        },
    ],
} as HogFlow

const BATCH_JOB = {
    id: '0192f0aa-1111-2222-3333-444455556666',
    status: 'completed',
    created_at: '2026-09-08T09:00:00.000Z',
    updated_at: '2026-09-08T09:04:00.000Z',
    created_by: { email: 'marketer@example.com' },
    filters: { properties: [] },
    variables: {},
}

const TRUNCATION_LOG = [
    BATCH_JOB.id,
    '2026-09-08T09:03:12.000Z',
    'warn',
    'Audience limit reached. This project allows at most 1000 recipients in one batch run, so 1000 were ' +
        'enrolled and the rest did not receive this workflow. Narrow the audience with filters to reach ' +
        'everyone you intend to.',
]

const meta: Meta<typeof WorkflowBatchInvocations> = {
    title: 'Products/Workflows/BatchInvocations',
    component: WorkflowBatchInvocations,
    parameters: {
        layout: 'padded',
        testOptions: { waitForLoadersToDisappear: true },
    },
    decorators: [
        mswDecorator({
            get: {
                // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
                '/api/environments/:team_id/hog_flows/:id/': BATCH_WORKFLOW,
                // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
                '/api/environments/:team_id/hog_flows/:id/batch_jobs': [BATCH_JOB],
                // nosemgrep: no-environments-api-urls-frontend -- api.hogFlows has not migrated to generated project routes.
                '/api/environments/:team_id/hog_flows/:id/schedules': [],
            },
            post: {
                '/api/environments/:team_id/query/HogQLQuery/': async ({ request }) => {
                    const body = (await request.json()) as { query?: { query?: string } }
                    const query = body.query?.query ?? ''
                    // The run log and the per-person invocations table both read this endpoint;
                    // only the log query is what this story is about.
                    return [200, { results: query.includes('log_entries') ? [TRUNCATION_LOG] : [] }]
                },
            },
        }),
    ],
}
export default meta

export const RunTruncatedAtTheAudienceLimit: StoryFn = () => (
    <BindLogic logic={workflowLogic} props={LOGIC_PROPS}>
        <WorkflowBatchInvocations id={LOGIC_PROPS.id!} />
    </BindLogic>
)
