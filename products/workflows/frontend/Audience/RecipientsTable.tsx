import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTable, LemonTableColumns, LemonTag, Link } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { urls } from 'scenes/urls'

import type { RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { optOutCategoriesLogic } from '../OptOuts/optOutCategoriesLogic'
import { RECIPIENTS_PAGE_SIZE, recipientsLogic } from './recipientsLogic'
import { TopicStatusTag } from './TopicStatusTag'

// Below this width the persons and last sent columns fold into the recipient cell.
const WIDE_ONLY = 'hidden @min-[44rem]/recipients:table-cell'
const NARROW_ONLY = '@min-[44rem]/recipients:hidden'

function PersonsSummary({ recipient }: { recipient: RecipientApi }): JSX.Element {
    if (recipient.person_count === 0) {
        return <span className="text-xs text-secondary">No person</span>
    }
    if (recipient.person_count === 1 && recipient.persons.length === 1) {
        const [person] = recipient.persons
        return <span className="wrap-anywhere">{person.name ?? person.distinct_id}</span>
    }
    return <span>{`${recipient.person_count.toLocaleString()} persons`}</span>
}

function LastSent({ recipient }: { recipient: RecipientApi }): JSX.Element {
    return recipient.last_sent_at ? (
        <TZLabel time={recipient.last_sent_at} />
    ) : (
        <span className="text-xs text-secondary">None</span>
    )
}

function RecipientCell({ recipient }: { recipient: RecipientApi }): JSX.Element {
    return (
        <div className="flex flex-col gap-1 min-w-0">
            <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
                <Link to={urls.audienceRecipient(recipient.email)} className="font-medium wrap-anywhere">
                    <span translate="no">{recipient.email}</span>
                </Link>
                {recipient.suppression && (
                    <LemonTag type="danger" size="small">
                        Suppressed
                    </LemonTag>
                )}
            </div>
            <div className={`${NARROW_ONLY} flex flex-wrap gap-x-2 text-xs text-secondary`}>
                <PersonsSummary recipient={recipient} />
                <span>
                    <span>Last sent: </span>
                    <LastSent recipient={recipient} />
                </span>
            </div>
        </div>
    )
}

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

function openRecipientUnlessInnerLink(event: React.MouseEvent<HTMLElement>, email: string): void {
    if (!(event.target as HTMLElement).closest('a, button')) {
        router.actions.push(urls.audienceRecipient(email))
    }
}

export function RecipientsTable(): JSX.Element {
    const { recipients, pageLoading, hasNextPage, hasPreviousPage } = useValues(recipientsLogic)
    const { loadNextPage, loadPreviousPage } = useActions(recipientsLogic)
    const { categories } = useValues(optOutCategoriesLogic)

    const topicNames = Object.fromEntries(categories.map((category) => [category.key, category.name]))

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
            className: WIDE_ONLY,
            render: (_, recipient) => <PersonsSummary recipient={recipient} />,
        },
        {
            title: 'Last sent (30 days)',
            key: 'last_sent_at',
            className: WIDE_ONLY,
            tooltip: 'When an email was last sent to this address. Sends older than 30 days are not shown.',
            render: (_, recipient) => <LastSent recipient={recipient} />,
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
                onRow={(recipient) => ({
                    className: 'cursor-pointer',
                    onClick: (event) => openRecipientUnlessInnerLink(event, recipient.email),
                })}
                pagination={{
                    controlled: true,
                    pageSize: RECIPIENTS_PAGE_SIZE,
                    useUrl: false,
                    onForward: hasNextPage ? loadNextPage : undefined,
                    onBackward: hasPreviousPage ? loadPreviousPage : undefined,
                }}
                data-attr="audience-recipients-table"
            />
        </div>
    )
}
