import { useActions, useValues } from 'kea'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'
import { organizationLogic } from 'scenes/organizationLogic'
import { urls } from 'scenes/urls'

import MailHog from '~/assets/hedgehog/mail-hog.png'
import { SubscriptionResourceType, SubscriptionType } from '~/types'

import { subscriptionsLogic } from '../subscriptionsLogic'
import { SubscriptionBaseProps } from '../utils'
import { AIPromptReportsLink, SubscriptionEmptyState, SubscriptionListItem } from './SubscriptionOverviewComponents'

interface ManageSubscriptionsProps extends SubscriptionBaseProps {
    onCancel: () => void
    onSelect: (value: number | 'new', resourceType?: SubscriptionResourceType) => void
}

export function ManageSubscriptions({
    insightShortId,
    dashboardId,
    onCancel,
    onSelect,
}: ManageSubscriptionsProps): JSX.Element {
    const logic = subscriptionsLogic({
        insightShortId,
        dashboardId,
    })

    const { subscriptions, subscriptionsLoading, deliveringSubscriptionId, togglingEnabledId } = useValues(logic)
    const { deleteSubscription, deliverSubscription, setSubscriptionEnabled } = useActions(logic)

    const subscriptionResourceNoun = !insightShortId && dashboardId ? 'dashboard' : 'insight'
    const hasResourceSubs = subscriptions.length > 0
    const aiPromptReportsEnabled = useFeatureFlag('SUBSCRIPTION_AI_PROMPT')
    const { currentOrganization } = useValues(organizationLogic)
    const showAiPromptReportsLink =
        aiPromptReportsEnabled &&
        !!currentOrganization?.is_ai_data_processing_approved &&
        (!!insightShortId || !!dashboardId)
    const loading = subscriptionsLoading && !hasResourceSubs

    const renderItem = (sub: SubscriptionType): JSX.Element => (
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
    )

    return (
        <>
            <LemonModal.Header>
                <div>
                    <h3>Manage subscriptions</h3>
                    <p className="text-sm text-secondary mb-0">
                        Subscriptions automatically send snapshots and reports to Slack or email on a schedule.
                    </p>
                </div>
            </LemonModal.Header>
            <LemonModal.Content>
                {loading ? (
                    <div className="deprecated-space-y-2">
                        <LemonSkeleton className="w-1/2 h-4" />
                        <LemonSkeleton.Row repeat={2} />
                    </div>
                ) : (
                    <div className="deprecated-space-y-4">
                        <div className="deprecated-space-y-2">
                            {hasResourceSubs ? (
                                <>
                                    <div>
                                        <strong>{subscriptions.length}</strong>{' '}
                                        {pluralize(subscriptions.length, 'subscription', 'subscriptions', false)}
                                    </div>
                                    <div className="max-h-[60vh] overflow-y-auto flex flex-col gap-2">
                                        {subscriptions.map(renderItem)}
                                    </div>
                                </>
                            ) : (
                                <SubscriptionEmptyState
                                    illustration={MailHog}
                                    title={`${capitalizeFirstLetter(subscriptionResourceNoun)} subscriptions`}
                                    description={`Send an up-to-date snapshot of this ${subscriptionResourceNoun} to Slack or email on a schedule.`}
                                    actionLabel="Create subscription"
                                    actionType="primary"
                                    prominence="featured"
                                    onAction={() => onSelect('new')}
                                />
                            )}
                        </div>

                        {showAiPromptReportsLink && (
                            <div className="border-t pt-3">
                                <AIPromptReportsLink />
                            </div>
                        )}
                    </div>
                )}
            </LemonModal.Content>

            <LemonModal.Footer>
                <div className="flex-1 flex gap-2">
                    {hasResourceSubs ? (
                        <LemonButton type="secondary" onClick={() => onSelect('new')}>
                            Add subscription
                        </LemonButton>
                    ) : null}
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
