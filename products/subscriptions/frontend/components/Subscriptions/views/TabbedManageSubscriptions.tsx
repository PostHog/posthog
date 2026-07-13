import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { urls } from 'scenes/urls'

import { SubscriptionType } from '~/types'

import { isSubscriptionEnabled } from '../../../scenes/components/SubscriptionsTable'
import { subscriptionsLogic } from '../subscriptionsLogic'
import { SubscriptionsLogicProps } from '../utils'
import { SubscriptionListItem } from './ManageSubscriptions'

const PAGE_SIZE = 10

export type SubscriptionTabKey = 'resource' | 'insights' | 'ai'

interface SubscriptionTabConfig {
    key: SubscriptionTabKey
    label: string
    subscriptions: SubscriptionType[]
    loading: boolean
    emptyMessage: string
}

interface TabbedManageSubscriptionsProps extends SubscriptionsLogicProps {
    onCancel: () => void
    onSelect: (value: number | 'new') => void
    // Tab state is owned by the parent modal: this component unmounts while a subscription
    // is being edited, so local state would snap back to the first tab on return.
    activeTab: SubscriptionTabKey
    onChangeTab: (tab: SubscriptionTabKey) => void
}

interface SubscriptionTabListProps {
    logicProps: SubscriptionsLogicProps
    paginationId: string
    subscriptions: SubscriptionType[]
    loading: boolean
    emptyMessage: string
    onSelect: (id: number) => void
}

// Scrollable, paginated list of subscriptions for a single tab. Pagination keeps the modal
// usable when a project accumulates a large number of subscriptions.
function SubscriptionTabList({
    logicProps,
    paginationId,
    subscriptions,
    loading,
    emptyMessage,
    onSelect,
}: SubscriptionTabListProps): JSX.Element {
    const logic = subscriptionsLogic(logicProps)
    const { deliveringSubscriptionId, togglingEnabledId } = useValues(logic)
    const { deleteSubscription, deliverSubscription, setSubscriptionEnabled } = useActions(logic)
    // Disabled subscriptions sort to the bottom so active ones stay visible first.
    const orderedSubscriptions = useMemo(
        () => [...subscriptions].sort((a, b) => Number(isSubscriptionEnabled(b)) - Number(isSubscriptionEnabled(a))),
        [subscriptions]
    )
    const pagination = usePagination(orderedSubscriptions, { pageSize: PAGE_SIZE }, paginationId)

    if (loading && subscriptions.length === 0) {
        return (
            <div className="deprecated-space-y-2 py-2">
                <LemonSkeleton.Row repeat={3} />
            </div>
        )
    }

    if (subscriptions.length === 0) {
        return <div className="text-secondary py-6 text-center">{emptyMessage}</div>
    }

    return (
        <div className="flex flex-col gap-2">
            <div className="max-h-[50vh] overflow-y-auto flex flex-col gap-2">
                {pagination.dataSourcePage.map((sub) => (
                    <SubscriptionListItem
                        key={sub.id}
                        subscription={sub}
                        onClick={() => onSelect(sub.id)}
                        onDelete={() => deleteSubscription(sub.id)}
                        onDeliver={() => deliverSubscription(sub.id)}
                        onToggleEnabled={(enabled) => setSubscriptionEnabled(sub.id, enabled)}
                        isDelivering={deliveringSubscriptionId === sub.id}
                        isToggling={togglingEnabledId === sub.id}
                    />
                ))}
            </div>
            <PaginationControl {...pagination} nouns={['subscription', 'subscriptions']} />
        </div>
    )
}

export function TabbedManageSubscriptions({
    insightShortId,
    dashboardId,
    onCancel,
    onSelect,
    activeTab,
    onChangeTab,
}: TabbedManageSubscriptionsProps): JSX.Element {
    const logicProps: SubscriptionsLogicProps = { insightShortId, dashboardId }
    const {
        subscriptions,
        subscriptionsLoading,
        insightSubscriptions,
        insightSubscriptionsLoading,
        aiSubscriptions,
        aiSubscriptionsLoading,
    } = useValues(subscriptionsLogic(logicProps))

    const isInsightContext = !!insightShortId

    // Tabs always render (including at count 0) so the available scopes stay discoverable.
    const tabConfigs: (SubscriptionTabConfig | false)[] = [
        {
            key: 'resource',
            label: isInsightContext ? 'This insight' : 'This dashboard',
            subscriptions,
            loading: subscriptionsLoading,
            emptyMessage: `No subscriptions for this ${isInsightContext ? 'insight' : 'dashboard'} yet.`,
        },
        !isInsightContext && {
            key: 'insights',
            label: 'Insights',
            subscriptions: insightSubscriptions,
            loading: insightSubscriptionsLoading,
            emptyMessage: "No subscriptions on this dashboard's insights yet.",
        },
        {
            key: 'ai',
            label: 'AI prompt reports',
            subscriptions: aiSubscriptions,
            loading: aiSubscriptionsLoading,
            emptyMessage: 'No AI prompt reports yet.',
        },
    ]
    const tabs: LemonTab<SubscriptionTabKey>[] = tabConfigs
        .filter((tab): tab is SubscriptionTabConfig => !!tab)
        .map(({ key, label, subscriptions, loading, emptyMessage }) => ({
            key,
            // No count during the initial fetch — "(0)" would read as empty rather than loading.
            label: loading && subscriptions.length === 0 ? label : `${label} (${subscriptions.length})`,
            content: (
                <SubscriptionTabList
                    logicProps={logicProps}
                    paginationId={key}
                    subscriptions={subscriptions}
                    loading={loading}
                    emptyMessage={emptyMessage}
                    onSelect={onSelect}
                />
            ),
        }))

    return (
        <>
            <LemonModal.Header>
                <h3>Subscriptions</h3>
            </LemonModal.Header>
            <LemonModal.Content>
                <LemonTabs
                    activeKey={activeTab}
                    onChange={onChangeTab}
                    tabs={tabs}
                    data-attr="manage-subscriptions-tabs"
                    rightSlotClassName="bg-transparent"
                    rightSlot={
                        <LemonButton type="primary" onClick={() => onSelect('new')} data-attr="add-subscription">
                            Add subscription
                        </LemonButton>
                    }
                />
            </LemonModal.Content>
            <LemonModal.Footer>
                <div className="flex-1">
                    <LemonButton type="tertiary" to={urls.subscriptions()}>
                        View all subscriptions
                    </LemonButton>
                </div>
                <LemonButton type="secondary" onClick={onCancel}>
                    Close
                </LemonButton>
            </LemonModal.Footer>
        </>
    )
}
