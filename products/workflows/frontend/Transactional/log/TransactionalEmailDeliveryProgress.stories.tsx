import { Meta, StoryFn } from '@storybook/react'

import type {
    TransactionalEmailLogDetailApi,
    TransactionalEmailLogEventApi,
} from 'products/messaging/frontend/generated/api.schemas'

import { TransactionalEmailDeliveryProgress } from './TransactionalEmailDeliveryProgress'

const meta: Meta<typeof TransactionalEmailDeliveryProgress> = {
    title: 'Scenes-App/Transactional/Email delivery progress',
    component: TransactionalEmailDeliveryProgress,
    parameters: { mockDate: '2026-06-15', testOptions: { snapshotBrowsers: [] } },
}
export default meta

function email(
    status: TransactionalEmailLogDetailApi['status'],
    timeline: TransactionalEmailLogEventApi[]
): TransactionalEmailLogDetailApi {
    return {
        message_id: '01977a3c-9a00-7000-8000-000000000001',
        created_at: '2026-06-15T09:00:00Z',
        status,
        status_at: timeline[timeline.length - 1].at,
        reason: timeline[timeline.length - 1].reason,
        recipient: 'maya.chen@example.com',
        workflow_id: '01977a3c-9a00-7000-8000-000000000002',
        template_id: '01977a3c-9a00-7000-8000-000000000003',
        template_name: 'Welcome email',
        sending_domain: 'example.com',
        opened: timeline.some((event) => event.kind === 'opened'),
        clicked: timeline.some((event) => event.kind === 'clicked'),
        timeline,
        subject: 'Welcome aboard',
        distinct_id: 'user_1',
        action_id: 'action_1',
        sensitive: false,
    }
}

const Template: StoryFn<typeof TransactionalEmailDeliveryProgress> = (args) => (
    <div className="@container max-w-200 p-4">
        <TransactionalEmailDeliveryProgress {...args} />
    </div>
)

export const OpenedAndClicked = Template.bind({})
OpenedAndClicked.args = {
    email: email('delivered', [
        { kind: 'queued', at: '2026-06-15T09:00:00Z', reason: null },
        { kind: 'sent', at: '2026-06-15T09:00:01Z', reason: null },
        { kind: 'delivered', at: '2026-06-15T09:00:03Z', reason: null },
        { kind: 'opened', at: '2026-06-15T09:12:40Z', reason: null },
        { kind: 'clicked', at: '2026-06-15T09:13:05Z', reason: null },
        { kind: 'opened', at: '2026-06-15T10:02:11Z', reason: null },
    ]),
}

export const Bounced = Template.bind({})
Bounced.args = {
    email: email('bounced', [
        { kind: 'queued', at: '2026-06-15T09:00:00Z', reason: null },
        { kind: 'sent', at: '2026-06-15T09:00:01Z', reason: null },
        { kind: 'bounced', at: '2026-06-15T09:00:04Z', reason: 'hard' },
    ]),
}
