import type { ReactNode } from 'react'

import { IconAI, IconEllipsis, IconGraph, IconPause, IconPlay, IconTrash } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { LemonMenu } from 'lib/lemon-ui/LemonMenu'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { SubscriptionResourceTypes, SubscriptionType } from '~/types'

import { subscriptionDestination } from '../../../scenes/components/subscriptionDestination'
import { isSubscriptionEnabled } from '../../../scenes/components/SubscriptionsTable'
import { targetTypeOptions } from '../utils'

const PROMPT_PREVIEW_MAX_CHARS = 80

interface SubscriptionListItemProps {
    subscription: SubscriptionType
    onClick: () => void
    onDelete?: () => void
    onDeliver?: () => void
    onToggleEnabled?: (enabled: boolean) => void
    isDelivering?: boolean
    isToggling?: boolean
}

function subscriptionListDestination(subscription: SubscriptionType): {
    icon: ReactNode
    label: string
    title: string
} {
    const destination = subscriptionDestination(subscription.target_type, subscription.target_value)
    return {
        icon: targetTypeOptions.find(({ value }) => value === subscription.target_type)?.icon,
        label: destination.label,
        title: destination.title,
    }
}

export function SubscriptionEmptyState({
    icon,
    illustration,
    title,
    description,
    actionLabel,
    actionType = 'secondary',
    prominence = 'compact',
    onAction,
}: {
    icon?: ReactNode
    illustration?: ReactNode
    title: string
    description: string
    actionLabel: string
    actionType?: 'primary' | 'secondary'
    prominence?: 'featured' | 'compact'
    onAction: () => void
}): JSX.Element {
    const isFeatured = prominence === 'featured'

    if (!isFeatured) {
        return (
            <LemonCard hoverEffect={false} className="p-2 bg-fill-secondary border-transparent">
                <div className="flex gap-2 items-center">
                    <div className="flex items-center justify-center rounded bg-surface-primary size-8 text-base shrink-0">
                        {icon}
                    </div>
                    <div className="min-w-0 flex-1">
                        <div className="text-sm font-medium">{title}</div>
                        <div className="text-xs text-secondary">{description}</div>
                    </div>
                    <LemonButton type="tertiary" size="xsmall" onClick={onAction} className="shrink-0">
                        {actionLabel}
                    </LemonButton>
                </div>
            </LemonCard>
        )
    }

    return (
        <LemonCard hoverEffect={false} className="p-6">
            <div className="flex flex-col items-start gap-3 @min-[30rem]/subscription-modal:flex-row">
                {illustration ? (
                    illustration
                ) : (
                    <div className="flex items-center justify-center rounded bg-surface-primary shrink-0 size-12 text-2xl">
                        {icon}
                    </div>
                )}
                <div className="flex flex-col gap-2 min-w-0">
                    <div>
                        <div className="font-semibold text-lg">{title}</div>
                        <div className="text-sm text-secondary">{description}</div>
                    </div>
                    <LemonButton type={actionType} size="small" onClick={onAction} className="self-start">
                        {actionLabel}
                    </LemonButton>
                </div>
            </div>
        </LemonCard>
    )
}

export function AIPromptReportsLink(): JSX.Element {
    return (
        <LemonCard hoverEffect={false} className="p-3 bg-fill-secondary border-transparent">
            <div className="flex flex-col gap-3 @min-[30rem]/subscription-modal:flex-row @min-[30rem]/subscription-modal:items-center">
                <div className="flex items-center justify-center rounded bg-surface-primary size-9 text-lg shrink-0">
                    <IconAI />
                </div>
                <div className="min-w-0 flex-1">
                    <div className="text-sm font-medium">Automate recurring analysis</div>
                    <div className="text-xs text-secondary">
                        Write a prompt once and get scheduled answers about your project in Slack or email.
                    </div>
                </div>
                <LemonButton
                    type="secondary"
                    size="small"
                    to={`${urls.subscriptions()}?tab=ai_prompt`}
                    className="self-start shrink-0 @min-[30rem]/subscription-modal:self-center"
                >
                    Explore AI prompt reports
                </LemonButton>
            </div>
        </LemonCard>
    )
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
    const destination = subscriptionListDestination(subscription)

    return (
        <div className="relative">
            <LemonButton type="secondary" onClick={onClick} data-attr="subscription-list-item" fullWidth>
                <div className="flex-auto p-2 min-w-0">
                    <div className="flex flex-col gap-1 min-w-0">
                        <div className="flex min-w-0 flex-col items-start gap-1 pr-8 @min-[30rem]/subscription-modal:flex-row @min-[30rem]/subscription-modal:items-center @min-[30rem]/subscription-modal:justify-between @min-[30rem]/subscription-modal:gap-4">
                            <div className="flex items-center gap-2 min-w-0">
                                <div className={`font-medium truncate ${enabled ? 'text-link' : 'text-muted'}`}>
                                    {subscription.title}
                                </div>
                                {!enabled && (
                                    <LemonTag type="danger" size="small">
                                        Disabled
                                    </LemonTag>
                                )}
                            </div>
                            <div
                                className="flex min-w-0 max-w-full items-center gap-1 text-xs text-secondary @min-[30rem]/subscription-modal:shrink-0"
                                title={destination.title}
                            >
                                {destination.icon}
                                <span className="max-w-40 truncate">{destination.label}</span>
                            </div>
                        </div>
                        {aiPrompt ? (
                            <Tooltip title={aiPromptTruncated ? aiPrompt : undefined}>
                                <div className="text-sm text-muted italic">{`"${aiPromptPreview}"`}</div>
                            </Tooltip>
                        ) : null}
                        {subscription.resource_type === SubscriptionResourceTypes.Insight &&
                        subscription.resource_name ? (
                            <div className="flex items-center gap-1 text-xs text-secondary">
                                <IconGraph />
                                <span>
                                    Insight: <span className="font-medium">{subscription.resource_name}</span>
                                </span>
                            </div>
                        ) : null}
                        <div className="text-xs text-secondary">
                            {capitalizeFirstLetter(subscription.summary)}
                            {selectedInsightsCount
                                ? ` · ${pluralize(selectedInsightsCount, 'insight', 'insights', true)}`
                                : null}
                        </div>
                        <div className="flex min-h-5 flex-col items-start gap-1 @min-[30rem]/subscription-modal:flex-row @min-[30rem]/subscription-modal:items-center @min-[30rem]/subscription-modal:justify-between @min-[30rem]/subscription-modal:gap-3">
                            {enabled && subscription.next_delivery_date && (
                                <div className="text-xs text-secondary shrink-0">
                                    Next delivery:{' '}
                                    <TZLabel
                                        time={subscription.next_delivery_date}
                                        formatDate="ddd, MMM D"
                                        formatTime="h:mm A"
                                        timestampStyle="absolute"
                                    />
                                </div>
                            )}
                            {subscription.created_by ? (
                                <div className="flex min-w-0 items-center gap-1 overflow-hidden text-xs text-tertiary opacity-60 @min-[30rem]/subscription-modal:ml-auto">
                                    <span>Created by</span>
                                    <ProfilePicture user={subscription.created_by} size="xs" showName />
                                </div>
                            ) : null}
                        </div>
                    </div>
                </div>
            </LemonButton>
            <div className="absolute right-2 top-2 z-10">
                <LemonMenu
                    items={[
                        onToggleEnabled
                            ? {
                                  label: enabled ? 'Disable subscription' : 'Enable subscription',
                                  icon: enabled ? <IconPause fontSize="12" /> : <IconPlay fontSize="12" />,
                                  onClick: () => onToggleEnabled(!enabled),
                                  'data-attr': 'subscription-list-item-toggle-enabled',
                              }
                            : false,
                        onDeliver && enabled
                            ? {
                                  label: 'Test delivery',
                                  icon: <IconPlay fontSize="12" />,
                                  onClick: onDeliver,
                                  'data-attr': 'subscription-list-item-manual-deliver',
                              }
                            : false,
                        onDelete
                            ? {
                                  label: 'Delete subscription',
                                  icon: <IconTrash fontSize="12" />,
                                  onClick: onDelete,
                                  status: 'danger' as const,
                                  'data-attr': 'subscription-list-item-delete',
                              }
                            : false,
                    ]}
                >
                    <LemonButton
                        type="tertiary"
                        size="xsmall"
                        icon={sideActionBusy ? <Spinner /> : <IconEllipsis />}
                        disabled={sideActionBusy}
                        aria-label="Subscription actions"
                        data-attr="subscription-list-item-actions"
                    />
                </LemonMenu>
            </div>
        </div>
    )
}
