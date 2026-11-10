import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, waitFor } from '@testing-library/react'
import { Provider } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AccessControlResourceType, AppContext } from '~/types'

import { sendErrorActions } from './broadcastLifecycle'
import { BroadcastSendErrorBanner } from './BroadcastSendErrorBanner'

const BROKEN_MERGE_TAG = '[Action:email] Errored: invalid value expression: "person.properties.nme"'
const PROVIDER_OUTAGE = '[Action:email] Errored: Failed to send email via SES: service unavailable'

describe('BroadcastSendErrorBanner', () => {
    const priorAppContext = window.POSTHOG_APP_CONTEXT

    afterEach(() => {
        cleanup()
        window.POSTHOG_APP_CONTEXT = priorAppContext
    })

    it.each([
        {
            grants: 'broadcast viewer',
            workflowAccess: AccessControlLevel.Editor,
            broadcastAccess: AccessControlLevel.Viewer,
            errorLog: BROKEN_MERGE_TAG,
            canMoveToDraft: true,
            label: 'Stop and edit',
            runs: false,
        },
        {
            grants: 'broadcast editor',
            workflowAccess: AccessControlLevel.Editor,
            broadcastAccess: AccessControlLevel.Editor,
            errorLog: BROKEN_MERGE_TAG,
            canMoveToDraft: true,
            label: 'Stop and edit',
            runs: true,
        },
        {
            grants: 'workflows viewer',
            workflowAccess: AccessControlLevel.Viewer,
            broadcastAccess: AccessControlLevel.Editor,
            errorLog: BROKEN_MERGE_TAG,
            canMoveToDraft: false,
            label: 'Fix and send again',
            runs: false,
        },
        {
            grants: 'workflows viewer',
            workflowAccess: AccessControlLevel.Viewer,
            broadcastAccess: AccessControlLevel.Editor,
            errorLog: PROVIDER_OUTAGE,
            canMoveToDraft: false,
            label: 'Send again',
            runs: false,
        },
        {
            grants: 'workflows editor',
            workflowAccess: AccessControlLevel.Editor,
            broadcastAccess: AccessControlLevel.Viewer,
            errorLog: PROVIDER_OUTAGE,
            canMoveToDraft: false,
            label: 'Send again',
            runs: true,
        },
    ])(
        'lets a $grants click $label on a failed send: $runs',
        async ({ workflowAccess, broadcastAccess, errorLog, canMoveToDraft, label, runs }) => {
            window.POSTHOG_APP_CONTEXT = {
                ...priorAppContext,
                resource_access_control: {
                    ...priorAppContext?.resource_access_control,
                    [AccessControlResourceType.Workflow]: workflowAccess,
                },
            } as AppContext
            useMocks({
                post: {
                    '/api/environments/:team_id/query/:kind/': async ({ request }) => {
                        const query = JSON.stringify(await request.json())
                        if (query.includes('log_entries')) {
                            return { results: [[errorLog]] }
                        }
                        if (query.includes('email_link_clicked_by_link')) {
                            return { results: [] }
                        }
                        return {
                            results: [
                                [40, 'email_sent', 'email'],
                                [3, 'failed', 'email'],
                            ],
                        }
                    },
                },
            })
            initKeaTests()
            const onMoveToDraft = jest.fn()
            const onSendAgain = jest.fn()
            const { fixAction, resendAction } = sendErrorActions({
                userAccessLevel: broadcastAccess,
                canMoveToDraft,
                canEditContent: true,
                onMoveToDraft,
                onSendAgain,
            })

            render(
                <Provider>
                    <BroadcastSendErrorBanner
                        runId="run-1"
                        runStartedAt="2026-10-19T22:28:56Z"
                        channel="email"
                        fixAction={fixAction}
                        resendAction={resendAction}
                    />
                </Provider>
            )

            await waitFor(() =>
                expect(document.querySelector('[data-attr="broadcast-send-error-action"]')).toHaveTextContent(label)
            )
            fireEvent.click(document.querySelector('[data-attr="broadcast-send-error-action"]')!)

            expect(onMoveToDraft.mock.calls.length + onSendAgain.mock.calls.length).toBe(runs ? 1 : 0)
        }
    )
})
