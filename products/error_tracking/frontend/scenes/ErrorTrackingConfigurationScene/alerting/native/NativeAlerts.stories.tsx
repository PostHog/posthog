import type { Meta, StoryObj } from '@storybook/react'
import { useLayoutEffect } from 'react'

import { useStorybookMocks } from '~/mocks/browser'

import { ErrorTrackingAlertApi, ErrorTrackingAlertPreviewApi } from '../../../../generated/api.schemas'
import { NativeAlertEditor } from './NativeAlertEditor'
import { nativeAlertEditorLogic } from './nativeAlertEditorLogic'
import { NativeAlertsList } from './NativeAlertsList'

// The Alerts section of the alerting settings page: the card list, then the editor with
// its Slack preview. The states worth a snapshot are a healthy alert next to a failing one,
// and the editor open on an existing alert so the two-column layout is covered.

const SLACK_INTEGRATION = {
    id: 7,
    kind: 'slack',
    display_name: 'PostHog workspace',
    config: { team: { name: 'PostHog' } },
    created_at: '2026-08-01T00:00:00Z',
    created_by: null,
    errors: '',
}

const ALERTS: ErrorTrackingAlertApi[] = [
    {
        id: '01990000-0000-7000-8000-000000000001',
        name: 'Production errors',
        enabled: true,
        triggers: ['issue_created', 'issue_reopened'],
        filters: { properties: [{ key: 'environment', value: 'production', type: 'event', operator: 'exact' }] },
        throttle_seconds: 3600,
        destinations: [
            {
                id: '01990000-0000-7000-8000-000000000011',
                channel_type: 'slack',
                integration_id: 7,
                config: { channel: 'C0123', channel_name: '#alerts-backend' },
                last_delivered_at: '2026-09-02T10:42:00Z',
                last_failure_at: null,
                last_error: '',
                consecutive_failures: 0,
            },
        ],
        created_at: '2026-08-20T00:00:00Z',
        updated_at: '2026-09-02T10:42:00Z',
    },
    {
        id: '01990000-0000-7000-8000-000000000002',
        name: 'Checkout spikes',
        enabled: true,
        triggers: ['issue_spiking'],
        filters: {
            properties: [{ key: '$current_url', value: '/checkout', type: 'event', operator: 'icontains' }],
        },
        throttle_seconds: 0,
        destinations: [
            {
                id: '01990000-0000-7000-8000-000000000012',
                channel_type: 'slack',
                integration_id: 7,
                config: { channel: 'C0456', channel_name: '#payments' },
                last_delivered_at: null,
                last_failure_at: '2026-09-02T09:00:00Z',
                last_error: 'Slack error: not_in_channel',
                consecutive_failures: 3,
            },
        ],
        created_at: '2026-08-25T00:00:00Z',
        updated_at: '2026-09-02T09:00:00Z',
    },
] as unknown as ErrorTrackingAlertApi[]

const PREVIEW: ErrorTrackingAlertPreviewApi = {
    issue_id: '01990000-0000-7000-8000-0000000000aa',
    messages: [
        {
            kind: 'root',
            event: '$error_tracking_issue_created',
            text: "🔴 New issue: TypeError: Cannot read properties of undefined (reading 'id')",
            blocks: [
                {
                    type: 'header',
                    text: {
                        type: 'plain_text',
                        text: "🔴 New issue: TypeError: Cannot read properties of undefined (reading 'id')",
                    },
                },
                { type: 'section', text: { type: 'plain_text', text: 'at CheckoutForm.submit (checkout.tsx:142)' } },
                { type: 'context', elements: [{ type: 'mrkdwn', text: 'Status: Active' }] },
                { type: 'actions', elements: [{ type: 'button', text: { type: 'plain_text', text: 'View issue' } }] },
            ],
        },
        {
            kind: 'reply',
            event: '$error_tracking_issue_assigned',
            text: '👤 Assigned by dev@example.com',
            blocks: null,
        },
        {
            kind: 'reply',
            event: '$error_tracking_issue_resolved',
            text: '✅ Resolved by dev@example.com',
            blocks: null,
        },
        {
            kind: 'root_edit',
            event: '$error_tracking_issue_resolved',
            text: "🔴 New issue: TypeError: Cannot read properties of undefined (reading 'id')",
            blocks: [
                {
                    type: 'header',
                    text: {
                        type: 'plain_text',
                        text: "🔴 New issue: TypeError: Cannot read properties of undefined (reading 'id')",
                    },
                },
                { type: 'section', text: { type: 'plain_text', text: 'at CheckoutForm.submit (checkout.tsx:142)' } },
                { type: 'context', elements: [{ type: 'mrkdwn', text: 'Status: Resolved' }] },
                { type: 'actions', elements: [{ type: 'button', text: { type: 'plain_text', text: 'View issue' } }] },
            ],
        },
    ],
}

function Section({ openAlert }: { openAlert?: ErrorTrackingAlertApi }): JSX.Element {
    useStorybookMocks({
        get: {
            '/api/projects/:id/error_tracking/alerts/': { count: ALERTS.length, results: ALERTS },
            '/api/projects/:id/error_tracking/alerts/preview/': PREVIEW,
            '/api/environments/:id/integrations/': { count: 1, results: [SLACK_INTEGRATION] },
            '/api/projects/:id/integrations/': { count: 1, results: [SLACK_INTEGRATION] },
            '/api/environments/:id/integrations/:intId/channels': {
                channels: [
                    { id: 'C0123', name: 'alerts-backend', is_private: false, is_member: true, is_ext_shared: false },
                    { id: 'C0456', name: 'payments', is_private: false, is_member: false, is_ext_shared: false },
                ],
            },
        },
    })
    useLayoutEffect(() => {
        if (openAlert) {
            nativeAlertEditorLogic.mount()
            nativeAlertEditorLogic.actions.openEditor(openAlert)
        }
    }, [openAlert])
    return (
        <div className="w-[900px] p-4">
            <NativeAlertsList />
            {/* Portals fall outside the snapshot root, so the open editor renders in place. */}
            <NativeAlertEditor inline={Boolean(openAlert)} />
        </div>
    )
}

const meta: Meta<typeof Section> = {
    title: 'Scenes-App/ErrorTracking/Alerts',
    component: Section,
    parameters: { layout: 'padded', viewMode: 'story', mockDate: '2026-09-02T12:00:00Z' },
}
export default meta

type Story = StoryObj<typeof Section>

export const List: Story = {}

export const EditorOpen: Story = {
    args: { openAlert: ALERTS[0] },
}
