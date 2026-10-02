import { BindLogic, useActions, useValues } from 'kea'

import { LemonBanner, LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import { optOutCategoriesLogic } from '../OptOuts/optOutCategoriesLogic'
import { recipientTimelineLogic } from './recipientTimelineLogic'
import { RecipientTimelineEvent } from './recipientTimelineQuery'

const ALL_MARKETING_TOPIC_ID = '$all'

const EVENT_LABELS: Record<string, string> = {
    $workflows_email_sent: 'Sent',
    $workflows_email_failed: 'Failed to send',
    $workflows_email_delivered: 'Delivered',
    $workflows_email_opened: 'Opened',
    $workflows_email_link_clicked: 'Clicked a link',
    $workflows_email_bounced: 'Bounced',
    // The provider reports a spam complaint as a block.
    $workflows_email_blocked: 'Marked as spam',
    $workflows_email_unsubscribed: 'Unsubscribed',
}

function TimelineDetails({
    timelineEvent,
    topicNames,
}: {
    timelineEvent: RecipientTimelineEvent
    topicNames: Record<string, string>
}): JSX.Element {
    if (timelineEvent.topicId) {
        const topicName =
            timelineEvent.topicId === ALL_MARKETING_TOPIC_ID
                ? 'All marketing'
                : (topicNames[timelineEvent.topicId] ?? 'A deleted topic')
        return <span className="text-secondary">{topicName}</span>
    }
    return (
        <div className="flex flex-col min-w-0">
            {timelineEvent.subject && <span className="wrap-anywhere">{timelineEvent.subject}</span>}
            {timelineEvent.linkUrl && (
                <span className="text-xs text-secondary wrap-anywhere">{timelineEvent.linkUrl}</span>
            )}
        </div>
    )
}

function RecipientTimelineTable(): JSX.Element {
    const { timeline, timelineLoading, loadFailed } = useValues(recipientTimelineLogic)
    const { loadRecipientTimeline } = useActions(recipientTimelineLogic)
    const { categories } = useValues(optOutCategoriesLogic)

    if (loadFailed) {
        return (
            <LemonBanner
                type="error"
                action={{
                    children: 'Try again',
                    onClick: loadRecipientTimeline,
                    'data-attr': 'audience-recipient-timeline-retry',
                }}
            >
                Couldn't load the email activity for this address.
            </LemonBanner>
        )
    }

    const topicNames = Object.fromEntries(categories.map((topic) => [topic.id, topic.name]))
    const columns: LemonTableColumns<RecipientTimelineEvent> = [
        {
            title: 'When',
            key: 'timestamp',
            width: 0,
            render: (_, timelineEvent) => <TZLabel time={timelineEvent.timestamp} />,
        },
        {
            title: 'What happened',
            key: 'event',
            width: 0,
            render: (_, timelineEvent) => (
                <span className="font-medium whitespace-nowrap">
                    {EVENT_LABELS[timelineEvent.event] ?? timelineEvent.event}
                </span>
            ),
        },
        {
            title: 'Details',
            key: 'details',
            render: (_, timelineEvent) => <TimelineDetails timelineEvent={timelineEvent} topicNames={topicNames} />,
        },
    ]

    return (
        <LemonTable
            columns={columns}
            dataSource={timeline ?? []}
            loading={timelineLoading}
            loadingSkeletonRows={5}
            rowKey={(timelineEvent, index) => `${timelineEvent.timestamp}-${timelineEvent.event}-${index}`}
            pagination={{ pageSize: 20 }}
            emptyState="No email activity for this address yet."
            data-attr="audience-recipient-timeline"
        />
    )
}

export function RecipientTimeline({ email }: { email: string }): JSX.Element {
    return (
        <BindLogic logic={recipientTimelineLogic} props={{ email }}>
            <RecipientTimelineTable />
        </BindLogic>
    )
}
