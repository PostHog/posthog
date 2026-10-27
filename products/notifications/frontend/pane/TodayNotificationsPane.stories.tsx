import { Meta, StoryObj } from '@storybook/react'

import { cn } from '@posthog/quill'

import { FEATURE_FLAGS } from 'lib/constants'
import { dayjs } from 'lib/dayjs'

import { mswDecorator } from '~/mocks/browser'

import { NotificationEventApi, UnreadSummaryApi } from '../generated/api.schemas'
import { NotificationsPaneHeaderActions } from './NotificationsPaneHeaderActions'
import { TodayNotificationsPane } from './TodayNotificationsPane'

type StoryArgs = { narrow: boolean }

const NOW = '2026-10-27T15:00:00Z'
const PROJECT_ID = 997

function ago(amount: number, unit: 'minute' | 'hour' | 'day'): string {
    return dayjs(NOW).subtract(amount, unit).toISOString()
}

function notification(
    overrides: Partial<NotificationEventApi> & Pick<NotificationEventApi, 'id'>
): NotificationEventApi {
    return {
        team_id: PROJECT_ID,
        notification_type: 'comment_mention',
        priority: 'normal',
        title: '',
        body: '',
        read: false,
        read_at: null,
        archived: false,
        target_type: 'user',
        target_id: '1',
        resource_type: null,
        resource_id: '',
        source_url: '',
        source_type: null,
        source_id: null,
        metadata: null,
        created_at: NOW,
        ...overrides,
    }
}

const NOTIFICATIONS: NotificationEventApi[] = [
    notification({
        id: 'mention',
        title: 'Ana Silva mentioned you',
        body: 'Funnel: Q3 signups · "Can you check the drop on step 2 before Friday?"',
        resource_type: 'insight',
        resource_id: 'aB3dE9',
        source_type: 'insight',
        source_id: 'aB3dE9',
        metadata: { actor_name: 'Ana Silva' },
        created_at: ago(2, 'minute'),
    }),
    notification({
        id: 'approval',
        notification_type: 'approval_requested',
        title: 'Approval requested: new-checkout',
        body: 'Marco Rossi · Feature flags',
        resource_type: 'feature_flag',
        resource_id: '42',
        source_url: '/approvals/42',
        metadata: { actor_name: 'Marco Rossi' },
        created_at: ago(1, 'hour'),
    }),
    notification({
        id: 'critical',
        team_id: 998,
        notification_type: 'alert_firing',
        priority: 'critical',
        title: 'Signups dropped below 100 per hour',
        body: 'Alert on Daily signups · fired at 11:58',
        resource_type: 'insight',
        resource_id: 'kP9xQ2',
        source_type: 'insight',
        source_id: 'kP9xQ2',
        created_at: ago(3, 'hour'),
    }),
    ...[21, 22, 50].map((hours, index) =>
        notification({
            id: `pipeline-${index}`,
            notification_type: 'pipeline_failure',
            target_type: 'team',
            title: 'Batch export to S3 failed',
            body: 'Access denied to bucket example-exports',
            resource_type: 'batch_export',
            resource_id: 'be-1',
            source_url: '/pipeline/batch-exports/be-1',
            created_at: ago(hours, 'hour'),
        })
    ),
    notification({
        id: 'sync',
        notification_type: 'materialization_failure',
        target_type: 'team',
        title: 'A data sync stopped',
        body: 'The Stripe sync failed 5 times in a row and is paused.',
        created_at: ago(26, 'hour'),
    }),
    notification({
        id: 'digest',
        notification_type: 'web_analytics_digest',
        target_type: 'team',
        title: 'Your weekly web analytics',
        body: 'Visitors 12.4k, +8%',
        source_url: '/web',
        read: true,
        created_at: ago(3, 'day'),
    }),
]

const SUMMARY: UnreadSummaryApi = { count: 6, direct_count: 2, has_critical: true }

function page(results: NotificationEventApi[]): Record<string, unknown> {
    return { count: results.length, next: null, previous: null, results, next_cursor: null }
}

function Pane({ narrow }: StoryArgs): JSX.Element {
    return (
        <div data-quill className={cn('Today flex h-160 flex-col bg-[var(--chrome)]', narrow ? 'w-60' : 'w-78')}>
            <div className="flex h-12 items-center justify-between px-3">
                <h2 className="m-0 text-base font-bold text-foreground">Notifications</h2>
                <NotificationsPaneHeaderActions />
            </div>
            <TodayNotificationsPane source="rail" />
        </div>
    )
}

const meta: Meta<StoryArgs> = {
    title: 'Products/Notifications/Today notifications pane',
    tags: ['test-skip'],
    parameters: {
        layout: 'padded',
        mockDate: NOW,
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.REAL_TIME_NOTIFICATIONS],
    },
    render: (args) => <Pane {...args} />,
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notifications/': page(NOTIFICATIONS),
                '/api/projects/:team_id/notifications/unread_count/': SUMMARY,
            },
        }),
    ],
}
export default meta

type Story = StoryObj<StoryArgs>

export const Default: Story = { args: { narrow: false } }

export const Narrow: Story = { args: { narrow: true } }

export const Empty: Story = {
    args: { narrow: false },
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/notifications/': page([]),
                '/api/projects/:team_id/notifications/unread_count/': {
                    count: 0,
                    direct_count: 0,
                    has_critical: false,
                },
            },
        }),
    ],
}
