import { useActions, useValues } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { LemonTag, Link, Tooltip } from '@posthog/lemon-ui'

import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonModal } from 'lib/lemon-ui/LemonModal'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { ProfileBubbles } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { SubscriptionResourceTypes, SubscriptionType } from '~/types'

import { isSubscriptionEnabled } from '../../../scenes/components/SubscriptionsTable'
import { subscriptionsLogic } from '../subscriptionsLogic'
import { SubscriptionBaseProps, formatNextDeliveryDate } from '../utils'

const PROMPT_PREVIEW_MAX_CHARS = 80
// AI subscriptions are supplementary context in this modal, so only a few are shown inline —
// the rest are reachable via the full subscriptions list.
const AI_PREVIEW_LIMIT = 3

interface SubscriptionListItemProps {
    subscription: SubscriptionType
    onClick: () => void
    onDelete?: () => void
    onDeliver?: () => void
    onToggleEnabled?: (enabled: boolean) => void
    isDelivering?: boolean
    isToggling?: boolean
}

export function SubscriptionListItem({
    subscription,
    onClick,
    onDelete,
    onDeliver,
    onToggleEnabled,
    isDelivering,
    isToggling,
}: SubscriptionListItemProps): JSX.Element {
    const selectedInsightsCount = subscription.dashboard_export_insights?.length
    const enabled = isSubscriptionEnabled(subscription)
    const sideActionBusy = isDelivering || isToggling

    const aiPrompt = subscription.resource_type === SubscriptionResourceTypes.AiPrompt ? subscription.prompt : null
    const aiPromptTruncated = aiPrompt && aiPrompt.length > PROMPT_PREVIEW_MAX_CHARS
    const aiPromptPreview = aiPromptTruncated ? `${aiPrompt.slice(0, PROMPT_PREVIEW_MAX_CHARS)}…` : aiPrompt

    return (
        <LemonButton
            type="secondary"
            onClick={onClick}
            data-attr="subscription-list-item"
            fullWidth
            sideAction={{
                icon: sideActionBusy ? <Spinner /> : <IconEllipsis />,
                disabled: sideActionBusy,
                dropdown: {
                    overlay: (
                        <>
                            {onToggleEnabled && (
                                <LemonButton
                                    onClick={() => onToggleEnabled(!enabled)}
                                    data-attr="subscription-list-item-toggle-enabled"
                                    fullWidth
                                    disabled={isToggling}
                                >
                                    {enabled ? 'Disable subscription' : 'Enable subscription'}
                                </LemonButton>
                            )}
                            {onDeliver && enabled && (
                                <LemonButton
                                    onClick={onDeliver}
                                    data-attr="subscription-list-item-manual-deliver"
                                    fullWidth
                                    disabled={isDelivering}
                                >
                                    Test delivery
                                </LemonButton>
                            )}
                            {onDelete && (
                                <LemonButton
                                    onClick={onDelete}
                                    data-attr="subscription-list-item-delete"
                                    status="danger"
                                    fullWidth
                                >
                                    Delete subscription
                                </LemonButton>
                            )}
                        </>
                    ),
                },
            }}
        >
            <div className="flex justify-between flex-auto items-center p-2">
                <div>
                    <div className={`font-medium ${enabled ? 'text-link' : 'text-muted'}`}>{subscription.title}</div>
                    {aiPrompt ? (
                        <Tooltip title={aiPromptTruncated ? aiPrompt : undefined}>
                            <div className="text-sm text-muted italic">{`"${aiPromptPreview}"`}</div>
                        </Tooltip>
                    ) : null}
                    {subscription.resource_type === SubscriptionResourceTypes.Insight && subscription.resource_name ? (
                        <div className="text-sm text-muted">{subscription.resource_name}</div>
                    ) : null}
                    <div className="text-sm text-text-3000">
                        {capitalizeFirstLetter(subscription.summary)}
                        {selectedInsightsCount
                            ? ` · ${pluralize(selectedInsightsCount, 'insight', 'insights', true)}`
                            : null}
                    </div>
                    {!enabled ? (
                        <LemonTag type="danger" size="small" className="mt-1">
                            Disabled
                        </LemonTag>
                    ) : subscription.next_delivery_date ? (
                        <div className="text-xs text-secondary">
                            Next delivery: {formatNextDeliveryDate(subscription.next_delivery_date)}
                        </div>
                    ) : null}
                </div>
                {subscription.target_type === 'email' ? (
                    <ProfileBubbles
                        limit={4}
                        people={subscription.target_value.split(',').map((email) => ({ email }))}
                    />
                ) : null}
                {subscription.target_type === 'slack' ? <IconSlack /> : null}
            </div>
        </LemonButton>
    )
}

interface ManageSubscriptionsProps extends SubscriptionBaseProps {
    onCancel: () => void
    onSelect: (value: number | 'new') => void
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

    const {
        subscriptions,
        subscriptionsLoading,
        aiSubscriptions,
        aiSubscriptionsLoading,
        deliveringSubscriptionId,
        togglingEnabledId,
    } = useValues(logic)
    const { deleteSubscription, deliverSubscription, setSubscriptionEnabled } = useActions(logic)

    const subscriptionResourceNoun = !insightShortId && dashboardId ? 'dashboard' : 'insight'
    const hasResourceSubs = subscriptions.length > 0
    const hasAiSubs = aiSubscriptions.length > 0
    const loading = (subscriptionsLoading || aiSubscriptionsLoading) && !hasResourceSubs && !hasAiSubs

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
                <h3> Manage Subscriptions</h3>
            </LemonModal.Header>
            <LemonModal.Content>
                {loading ? (
                    <div className="deprecated-space-y-2">
                        <LemonSkeleton className="w-1/2 h-4" />
                        <LemonSkeleton.Row repeat={2} />
                    </div>
                ) : !hasResourceSubs && !hasAiSubs ? (
                    <div className="flex flex-col p-4 items-center text-center">
                        <h3>There are no subscriptions for this {subscriptionResourceNoun}</h3>

                        <p>Once subscriptions are created they will display here. </p>

                        <LemonButton type="primary" onClick={() => onSelect('new')}>
                            Add subscription
                        </LemonButton>
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
                                    <div className="max-h-[50vh] overflow-y-auto flex flex-col gap-2">
                                        {subscriptions.map(renderItem)}
                                    </div>
                                </>
                            ) : (
                                <div className="text-muted">
                                    No subscriptions for this {subscriptionResourceNoun} yet.
                                </div>
                            )}
                        </div>

                        {hasAiSubs ? (
                            <div className="deprecated-space-y-2">
                                <div>
                                    <strong>{aiSubscriptions.length}</strong>{' '}
                                    {pluralize(
                                        aiSubscriptions.length,
                                        'prompt subscription',
                                        'prompt subscriptions',
                                        false
                                    )}
                                    <div className="text-xs text-muted">
                                        Not tied to this {subscriptionResourceNoun}, shared across your project.
                                    </div>
                                </div>
                                <div className="flex flex-col gap-2">
                                    {aiSubscriptions.slice(0, AI_PREVIEW_LIMIT).map(renderItem)}
                                </div>
                                {aiSubscriptions.length > AI_PREVIEW_LIMIT ? (
                                    <Link to={urls.subscriptions()} className="text-xs">
                                        View all {aiSubscriptions.length} prompt subscriptions
                                    </Link>
                                ) : null}
                            </div>
                        ) : null}
                    </div>
                )}
            </LemonModal.Content>

            <LemonModal.Footer>
                <div className="flex-1 flex gap-2">
                    {hasResourceSubs || hasAiSubs ? (
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
