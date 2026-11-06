import { Meta, StoryFn } from '@storybook/react'

import type { ActivityEvent } from './emailActivity'
import { buildActivityTimeline } from './emailActivity'
import { groupActivityRows } from './emailActivityGroups'
import { TransactionalEmailActivityRail } from './TransactionalEmailActivityRail'

const meta: Meta<typeof TransactionalEmailActivityRail> = {
    title: 'Scenes-App/Transactional/Email activity rail',
    component: TransactionalEmailActivityRail,
    parameters: { mockDate: '2026-06-15', testOptions: { snapshotBrowsers: [] } },
}
export default meta

const SENT_AT = '2026-06-15T09:00:00Z'

function event(uuid: string, timestamp: string, sessionId: string | null, name = '$pageview'): ActivityEvent {
    return {
        uuid,
        event: name,
        timestamp,
        url: null,
        pathname: '/pricing',
        sessionId,
        eventType: null,
        elementsChain: '',
    }
}

const timeline = buildActivityTimeline(
    [
        event('before', '2026-06-14T08:59:00Z', 'session-1'),
        event('after', '2026-06-15T09:03:00Z', 'session-2'),
        event('outcome', '2026-06-15T09:04:00Z', 'session-2', 'upgraded_plan'),
        event('no-session', '2026-06-15T14:00:00Z', null, 'invoice_paid'),
    ],
    [],
    SENT_AT
)

export const SessionsAroundTheSend: StoryFn = () => (
    <TransactionalEmailActivityRail
        before={groupActivityRows(timeline.before)}
        after={groupActivityRows(timeline.after)}
        sentAt={SENT_AT}
        failed={false}
        sendLabel="Email sent"
        sendDetail="Welcome email"
        comeback="Back in your app 1m after clicking the email"
        emptyAfter={null}
        hiddenBefore={2}
        onShowEarlier={() => {}}
        hiddenAfter={0}
        onShowLater={() => {}}
    />
)
