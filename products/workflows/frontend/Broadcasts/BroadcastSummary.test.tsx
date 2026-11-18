import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_PROJECT, MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { BindLogic, Provider } from 'kea'
import { router } from 'kea-router'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext, AvailableFeature } from '~/types'

import type { HogFlowApi, HogFlowBatchJobApi, HogFlowScheduleApi } from '../generated/api.schemas'
import { broadcastPreviewLogic } from './broadcastPreviewLogic'
import { BroadcastSummary } from './BroadcastSummary'
import { broadcastTestSendLogic } from './broadcastTestSendLogic'
import { broadcastWizardLogic } from './broadcastWizardLogic'

const BROADCAST_ID = 'broadcast-1'
const COPY_ID = 'broadcast-copy'

const BROKEN_MERGE_TAG = '[Action:email] Errored: invalid value expression: "person.properties.nme"'
const PROVIDER_OUTAGE = '[Action:email] Errored: Failed to send email via SES: service unavailable'

const WEEKLY: HogFlowScheduleApi = {
    id: 'schedule-1',
    rrule: 'FREQ=WEEKLY;INTERVAL=1',
    starts_at: '2026-10-19T22:00:00Z',
    status: 'active',
    next_run_at: '2026-10-26T22:00:00Z',
    created_at: '2026-10-01T00:00:00Z',
    updated_at: '2026-10-01T00:00:00Z',
} as HogFlowScheduleApi

const FAILED_RUN = {
    id: 'run-1',
    status: 'partially_failed',
    hog_flow: BROADCAST_ID,
    filters: {},
    created_at: '2026-10-19T22:28:56Z',
} as HogFlowBatchJobApi

function sentBroadcast(userAccessLevel: AccessControlLevel, schedules: HogFlowScheduleApi[]): HogFlowApi {
    return {
        id: BROADCAST_ID,
        name: 'October newsletter',
        version: 1,
        status: 'active',
        created_at: '2026-10-01T00:00:00Z',
        updated_at: '2026-10-01T00:00:00Z',
        trigger: { type: 'batch', filters: { properties: [] } },
        actions: [
            { id: 'trigger_node', name: 'Trigger', type: 'trigger', config: { type: 'batch', filters: {} } },
            {
                id: 'email_node',
                name: 'Email',
                type: 'function_email',
                config: { inputs: { email: { value: { subject: 'October news' } } } },
            },
            { id: 'exit_node', name: 'Exit', type: 'exit', config: { reason: 'Default exit' } },
        ],
        edges: [
            { from: 'trigger_node', to: 'email_node', type: 'continue' },
            { from: 'email_node', to: 'exit_node', type: 'continue' },
        ],
        schedules,
        user_access_level: userAccessLevel,
    } as unknown as HogFlowApi
}

describe('BroadcastSummary', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT

    afterEach(async () => {
        const cancel = screen.queryByText('Cancel')
        if (cancel) {
            fireEvent.click(cancel)
            await waitFor(() => {
                if (screen.queryByText('Cancel')) {
                    throw new Error('The dialog is still open')
                }
            })
        }
        cleanup()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    const editDialogOpen = (): boolean => !!screen.queryByText('Stop this broadcast and edit it?')
    const copyOpened = (): boolean => router.values.location.pathname.includes(COPY_ID)

    it.each([
        {
            grants: 'broadcast viewer',
            workflowAccess: AccessControlLevel.Editor,
            broadcastAccess: AccessControlLevel.Viewer,
            schedules: [WEEKLY],
            errorLog: BROKEN_MERGE_TAG,
            label: 'Stop and edit',
            outcome: editDialogOpen,
            allowed: false,
        },
        {
            grants: 'broadcast editor',
            workflowAccess: AccessControlLevel.Editor,
            broadcastAccess: AccessControlLevel.Editor,
            schedules: [WEEKLY],
            errorLog: BROKEN_MERGE_TAG,
            label: 'Stop and edit',
            outcome: editDialogOpen,
            allowed: true,
        },
        {
            grants: 'workflows viewer',
            workflowAccess: AccessControlLevel.Viewer,
            broadcastAccess: AccessControlLevel.Editor,
            schedules: [],
            errorLog: BROKEN_MERGE_TAG,
            label: 'Fix and send again',
            outcome: copyOpened,
            allowed: false,
        },
        {
            grants: 'workflows viewer',
            workflowAccess: AccessControlLevel.Viewer,
            broadcastAccess: AccessControlLevel.Editor,
            schedules: [],
            errorLog: PROVIDER_OUTAGE,
            label: 'Send again',
            outcome: copyOpened,
            allowed: false,
        },
        {
            grants: 'workflows editor',
            workflowAccess: AccessControlLevel.Editor,
            broadcastAccess: AccessControlLevel.Viewer,
            schedules: [],
            errorLog: PROVIDER_OUTAGE,
            label: 'Send again',
            outcome: copyOpened,
            allowed: true,
        },
    ])(
        'lets a $grants act on $label after a failed send: $allowed',
        async ({ workflowAccess, broadcastAccess, schedules, errorLog, label, outcome, allowed }) => {
            window.POSTHOG_APP_CONTEXT = {
                ...priorAppContext,
                resource_access_control: {
                    ...priorAppContext?.resource_access_control,
                    [AccessControlResourceType.Workflow]: workflowAccess,
                },
            } as AppContext
            useMocks({
                get: {
                    '/api/projects/:team_id/hog_flows/:id/': sentBroadcast(broadcastAccess, schedules),
                    '/api/projects/:team_id/hog_flows/:id/batch_jobs/': [FAILED_RUN],
                },
                post: {
                    '/api/projects/:team_id/hog_flows/': () => [
                        201,
                        { ...sentBroadcast(AccessControlLevel.Editor, []), id: COPY_ID, status: 'draft' },
                    ],
                    '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                        const query = JSON.stringify(await request.json())
                        if (query.includes('log_entries')) {
                            return [200, { results: [[errorLog]] }]
                        }
                        if (query.includes('email_link_clicked_by_link') || query.includes('groupArray')) {
                            return [200, { results: [] }]
                        }
                        return [
                            200,
                            {
                                results: [
                                    [40, 'email_sent', 'email'],
                                    [3, 'failed', 'email'],
                                ],
                            },
                        ]
                    },
                },
            })
            initKeaTests()
            const props = { id: BROADCAST_ID }

            render(
                <Provider>
                    <BindLogic logic={broadcastWizardLogic} props={props}>
                        <BindLogic logic={broadcastPreviewLogic} props={props}>
                            <BindLogic logic={broadcastTestSendLogic} props={props}>
                                <BroadcastSummary />
                            </BindLogic>
                        </BindLogic>
                    </BindLogic>
                </Provider>
            )

            await waitFor(() => expect(screen.getAllByText(label).length).toBeGreaterThan(0))
            await act(async () => {
                fireEvent.click(screen.getAllByText(label)[0])
            })

            const happened = await waitFor(() => expect(outcome()).toBe(true), { timeout: 500 }).then(
                () => true,
                () => false
            )
            expect(happened).toBe(allowed)
        }
    )

    it.each([
        { opened: 'by clicking the History tab', activityLink: false },
        { opened: 'from a copied activity link', activityLink: true },
    ])(
        'shows past versions read-only and each change with where it came from, opened $opened',
        async ({ activityLink }) => {
            window.POSTHOG_APP_CONTEXT = {
                ...priorAppContext,
                resource_access_control: {
                    ...priorAppContext?.resource_access_control,
                    [AccessControlResourceType.ActivityLog]: AccessControlLevel.Viewer,
                },
            } as AppContext
            useMocks({
                get: {
                    '/api/projects/:team_id/hog_flows/:id/': {
                        ...sentBroadcast(AccessControlLevel.Editor, []),
                        version: 2,
                    },
                    '/api/projects/:team_id/hog_flows/:id/batch_jobs/': [],
                    '/api/projects/:team_id/hog_flows/:id/revisions/': {
                        count: 2,
                        next: null,
                        previous: null,
                        results: [
                            { version: 2, created_by: null, created_at: '2026-10-20T09:00:00Z' },
                            { version: 1, created_by: null, created_at: '2026-10-19T09:00:00Z' },
                        ],
                    },
                    '/api/projects/:team_id/activity_log/': {
                        count: 1,
                        next: null,
                        previous: null,
                        results: [
                            {
                                id: 'activity-1',
                                activity: 'updated',
                                scope: 'HogFlow',
                                item_id: BROADCAST_ID,
                                created_at: '2026-10-20T09:00:00Z',
                                client: 'mcp',
                                user: { first_name: 'Ada', last_name: '', email: 'ada@example.com' },
                                detail: { name: 'October newsletter', changes: [] },
                            },
                        ],
                    },
                },
            })
            initKeaTests(true, MOCK_DEFAULT_TEAM, MOCK_DEFAULT_PROJECT, {
                ...MOCK_DEFAULT_ORGANIZATION,
                available_product_features: [{ key: AvailableFeature.AUDIT_LOGS, name: 'Audit logs' }],
            })
            if (activityLink) {
                router.actions.push(`/broadcasts/${BROADCAST_ID}`, { activity: 'activity-1' })
            }
            const props = { id: BROADCAST_ID }

            render(
                <Provider>
                    <BindLogic logic={broadcastWizardLogic} props={props}>
                        <BindLogic logic={broadcastPreviewLogic} props={props}>
                            <BindLogic logic={broadcastTestSendLogic} props={props}>
                                <BroadcastSummary />
                            </BindLogic>
                        </BindLogic>
                    </BindLogic>
                </Provider>
            )

            if (!activityLink) {
                await act(async () => {
                    fireEvent.click(await screen.findByText('History'))
                })
            }

            expect(await screen.findByText('v2')).toBeInTheDocument()
            expect(screen.getByText('v1')).toBeInTheDocument()
            // The first activity row waits on a one-time dynamic import of every product's describers.
            expect(await screen.findByText('via MCP', undefined, { timeout: 10000 })).toBeInTheDocument()
            expect(screen.queryByText('Restore as draft')).not.toBeInTheDocument()
        },
        15000
    )
})
