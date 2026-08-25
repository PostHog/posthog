import { useActions, useValues } from 'kea'
import { useMemo } from 'react'
import type { ReactNode } from 'react'

import { MailHog } from 'lib/components/hedgehogs'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { LemonTab, LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { PaginationControl, usePagination } from 'lib/lemon-ui/PaginationControl'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import { SubscriptionResourceType, SubscriptionType } from '~/types'

import { isSubscriptionEnabled } from '../../../scenes/components/SubscriptionsTable'
import { subscriptionsLogic } from '../subscriptionsLogic'
import { SubscriptionsLogicProps } from '../utils'
import { AIPromptReportsLink, SubscriptionEmptyState, SubscriptionListItem } from './SubscriptionOverviewComponents'

const PAGE_SIZE = 10
export type SubscriptionTabKey = 'resource' | 'insights'

interface SubscriptionTabConfig {
    key: SubscriptionTabKey
    label: string
    subscriptions: SubscriptionType[]
    loading: boolean
    emptyMessage: string
    description?: string
    footer?: ReactNode
    emptyState?: ReactNode
}

interface TabbedManageSubscriptionsProps extends SubscriptionsLogicProps {
    onCancel: () => void
    onSelect: (value: number | 'new', resourceType?: SubscriptionResourceType) => void
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
    description?: string
    footer?: ReactNode
    emptyState?: ReactNode
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
    description,
    footer,
    emptyState,
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
            <div className="flex flex-col gap-2 py-2">
                {description ? <div className="text-sm text-secondary">{description}</div> : null}
                <div className="deprecated-space-y-2">
                    <LemonSkeleton.Row repeat={3} />
                </div>
                {footer}
            </div>
        )
    }

    if (subscriptions.length === 0) {
        return (
            <div className="flex flex-col gap-2">
                {description ? <div className="text-sm text-secondary">{description}</div> : null}
                {emptyState || <div className="text-secondary py-6 text-center">{emptyMessage}</div>}
                {footer}
            </div>
        )
    }

    return (
        <div className="flex flex-col gap-2">
            {description ? <div className="text-sm text-secondary">{description}</div> : null}
            <div className="max-h-[60vh] overflow-y-auto flex flex-col gap-2">
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
            {footer}
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
    const { subscriptions, subscriptionsLoading, insightSubscriptions, insightSubscriptionsLoading } = useValues(
        subscriptionsLogic(logicProps)
    )
    const { currentOrganization } = useValues(organizationLogic)
    const aiPromptReportsAvailable =
        useFeatureFlag('SUBSCRIPTION_AI_PROMPT') && !!currentOrganization?.is_ai_data_processing_approved

    const isInsightContext = !!insightShortId

    // Tabs always render (including at count 0) so the available scopes stay discoverable.
    const tabConfigs: (SubscriptionTabConfig | false)[] = [
        {
            key: 'resource',
            label: isInsightContext ? 'This insight' : 'This dashboard',
            subscriptions,
            loading: subscriptionsLoading,
            emptyMessage: `No subscriptions for this ${
                isInsightContext ? 'insight' : 'dashboard'
            } yet. Add one to send an up-to-date snapshot to Slack or email on a schedule.`,
            emptyState: (
                <SubscriptionEmptyState
                    illustration={<MailHog className="object-contain shrink-0 w-24 h-20" />}
                    title={`${isInsightContext ? 'Insight' : 'Dashboard'} subscriptions`}
                    description={`Send an up-to-date snapshot of this ${
                        isInsightContext ? 'insight' : 'dashboard'
                    } to Slack or email on a schedule.`}
                    actionLabel="Create subscription"
                    actionType="primary"
                    prominence="featured"
                    onAction={() => onSelect('new')}
                />
            ),
            footer: aiPromptReportsAvailable ? (
                <div className="border-t pt-3">
                    <AIPromptReportsLink />
                </div>
            ) : undefined,
        },
        !isInsightContext && {
            key: 'insights',
            label: 'Insights',
            subscriptions: insightSubscriptions,
            loading: insightSubscriptionsLoading,
            emptyMessage:
                "No subscriptions on this dashboard's insights yet. Open an insight on this dashboard to create one.",
        },
    ]
    const tabs: LemonTab<SubscriptionTabKey>[] = tabConfigs
        .filter((tab): tab is SubscriptionTabConfig => !!tab)
        .map(({ key, label, subscriptions, loading, emptyMessage, description, footer, emptyState }) => ({
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
                    description={description}
                    footer={footer}
                    emptyState={emptyState}
                    onSelect={onSelect}
                />
            ),
        }))

    return (
        <>
            <LemonModal.Header>
                <div>
                    <h3>Subscriptions</h3>
                    <p className="text-sm text-secondary mb-0">
                        Subscriptions automatically send snapshots and reports to Slack or email on a schedule.
                    </p>
                </div>
            </LemonModal.Header>
            <LemonModal.Content>
                <LemonTabs
                    activeKey={activeTab}
                    onChange={onChangeTab}
                    tabs={tabs}
                    data-attr="manage-subscriptions-tabs"
                    rightSlotClassName="bg-transparent"
                    rightSlot={
                        activeTab === 'resource' ? (
                            <LemonButton type="primary" onClick={() => onSelect('new')} data-attr="add-subscription">
                                Add subscription
                            </LemonButton>
                        ) : undefined
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
