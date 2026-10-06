import { useValues } from 'kea'

import { LemonCard, LemonSkeleton } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'

import type { MessageCategoryApi, RecipientApi } from 'products/messaging/frontend/generated/api.schemas'

import { optOutCategoriesLogic } from '../OptOuts/optOutCategoriesLogic'
import { TopicStatusTag } from './TopicStatusTag'

type TopicStatus = RecipientApi['all_marketing']

function TopicRow({
    name,
    description,
    status,
}: {
    name: string
    description?: string
    status: TopicStatus
}): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-2 py-1" data-attr="audience-recipient-topic">
            <div className="flex flex-col min-w-0">
                <span className="font-medium wrap-anywhere">{name}</span>
                {description && <span className="text-xs text-secondary wrap-anywhere">{description}</span>}
            </div>
            <TopicStatusTag status={status} />
        </div>
    )
}

function explicitTopicStatus(recipient: RecipientApi, topicKey: string): TopicStatus | undefined {
    return Object.hasOwn(recipient.topics, topicKey) ? recipient.topics[topicKey] : undefined
}

function isShownTopic(topic: MessageCategoryApi, recipient: RecipientApi): boolean {
    return topic.category_type !== 'transactional' || explicitTopicStatus(recipient, topic.key) !== undefined
}

export function RecipientTopicsCard({ recipient }: { recipient: RecipientApi }): JSX.Element {
    const { categories, categoriesLoading } = useValues(optOutCategoriesLogic)
    const topics = categories.filter((topic) => isShownTopic(topic, recipient))

    return (
        <LemonCard hoverEffect={false} className="flex-1 min-w-72 flex flex-col gap-1">
            <h3 className="font-semibold m-0">Topics</h3>
            <div className="flex flex-col divide-y">
                <TopicRow
                    name="All marketing"
                    description="Every marketing topic at once"
                    status={recipient.all_marketing}
                />
                {categoriesLoading ? (
                    <LemonSkeleton className="h-8 my-1" repeat={2} />
                ) : (
                    topics.map((topic) => (
                        <TopicRow
                            key={topic.key}
                            name={topic.name}
                            description={topic.description}
                            status={explicitTopicStatus(recipient, topic.key) ?? 'NO_PREFERENCE'}
                        />
                    ))
                )}
            </div>
            <p className="m-0 text-xs text-secondary">
                {recipient.preferences_updated_at ? (
                    <>
                        Last changed <TZLabel time={recipient.preferences_updated_at} />
                    </>
                ) : (
                    'No preference recorded yet.'
                )}
            </p>
        </LemonCard>
    )
}
