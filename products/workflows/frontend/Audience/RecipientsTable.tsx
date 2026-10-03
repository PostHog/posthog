import { useActions, useValues } from 'kea'

import { LemonTable, LemonTableColumns } from '@posthog/lemon-ui'

import type { RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { audienceSceneLogic } from './audienceSceneLogic'
import { RecipientCell } from './RecipientCell'
import { RecipientLastSent } from './RecipientLastSent'
import { RecipientPersonsSummary } from './RecipientPersonsSummary'
import { recipientsLogic } from './recipientsLogic'
import { WIDE_RECIPIENTS_TABLE_ONLY } from './recipientsTableLayout'
import { TopicStatusTag } from './TopicStatusTag'

function TopicsCell({
    recipient,
    topicNames,
}: {
    recipient: RecipientApi
    topicNames: Record<string, string>
}): JSX.Element {
    const explicitTopics = Object.entries(recipient.topics)
    if (explicitTopics.length === 0) {
        return <span className="text-xs text-secondary">No preference on any topic</span>
    }
    return (
        <div className="flex flex-wrap gap-1">
            {explicitTopics.map(([topicKey, status]) => (
                <TopicStatusTag key={topicKey} status={status} topicName={topicNames[topicKey] ?? topicKey} />
            ))}
        </div>
    )
}

export function RecipientsTable(): JSX.Element {
    const { recipients, pageLoading, currentPage, hasNextPage, hasPreviousPage, topicNames } =
        useValues(recipientsLogic)
    const { loadNextPage, loadPreviousPage } = useActions(recipientsLogic)
    const { openRecipient } = useActions(audienceSceneLogic)

    const columns: LemonTableColumns<RecipientApi> = [
        {
            title: 'Recipient',
            key: 'email',
            render: (_, recipient) => <RecipientCell recipient={recipient} />,
        },
        {
            title: 'All marketing',
            key: 'all_marketing',
            render: (_, recipient) => <TopicStatusTag status={recipient.all_marketing} />,
        },
        {
            title: 'Topics',
            key: 'topics',
            render: (_, recipient) => <TopicsCell recipient={recipient} topicNames={topicNames} />,
        },
        {
            title: 'Persons',
            key: 'persons',
            className: WIDE_RECIPIENTS_TABLE_ONLY,
            render: (_, recipient) => <RecipientPersonsSummary recipient={recipient} />,
        },
        {
            title: 'Last sent (30 days)',
            key: 'last_sent_at',
            className: WIDE_RECIPIENTS_TABLE_ONLY,
            tooltip: 'When an email was last sent to this address. Sends older than 30 days are not shown.',
            render: (_, recipient) => <RecipientLastSent recipient={recipient} />,
        },
    ]

    return (
        <div className="@container/recipients">
            <LemonTable
                columns={columns}
                dataSource={recipients}
                rowKey="email"
                loading={pageLoading}
                loadingSkeletonRows={8}
                nouns={['recipient', 'recipients']}
                rowClassName="ph-no-capture"
                onRow={(recipient) => ({ onClick: () => openRecipient(recipient.email) })}
                emptyState="No recipients on this page"
                pagination={{
                    controlled: true,
                    useUrl: false,
                    currentPage: currentPage ?? undefined,
                    onForward: hasNextPage ? loadNextPage : undefined,
                    onBackward: hasPreviousPage ? loadPreviousPage : undefined,
                }}
                data-attr="audience-recipients-table"
            />
        </div>
    )
}
