import type { ReactNode } from 'react'

import { IconAI, IconEllipsis, IconGraph, IconLetter, IconPause, IconPlay, IconTrash } from '@posthog/icons'
import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { TZLabel } from 'lib/components/TZLabel'
import { IconSlack } from 'lib/lemon-ui/icons'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCard } from 'lib/lemon-ui/LemonCard'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'
import { urls } from 'scenes/urls'

import { SubscriptionResourceTypes, SubscriptionType } from '~/types'

import { isSubscriptionEnabled } from '../../../scenes/components/SubscriptionsTable'

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

function subscriptionDestination(subscription: SubscriptionType): { label: string; title: string } {
    const destinations = subscription.target_value
        .split(',')
        .map((destination) => destination.trim())
        .filter(Boolean)

    if (subscription.target_type === 'email') {
        return {
            label: destinations.length === 1 ? destinations[0] : `${destinations.length} recipients`,
            title: destinations.join(', '),
        }
    }

    const channels = destinations.map((destination) => destination.split('|')[1] || destination)
    return {
        label: channels.length === 1 ? channels[0] : `${channels.length} channels`,
        title: channels.join(', '),
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
            <div className="flex gap-3 items-start">
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
            <div className="flex gap-3 items-center">
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
                    type="tertiary"
                    size="xsmall"
                    to={`${urls.subscriptions()}?tab=ai_prompt`}
                    className="shrink-0"
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
    const destination = subscriptionDestination(subscription)

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
                                    icon={enabled ? <IconPause /> : <IconPlay />}
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
                                    icon={<IconPlay />}
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
                                    icon={<IconTrash />}
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
            <div className="flex-auto p-2 min-w-0">
                <div className="flex flex-col gap-1 min-w-0">
                    <div className="flex items-center justify-between gap-4">
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
                            className="flex items-center gap-1 text-xs text-secondary shrink-0"
                            title={destination.title}
                        >
                            {subscription.target_type === 'email' && <IconLetter />}
                            {subscription.target_type === 'slack' && <IconSlack />}
                            <span className="max-w-40 truncate">{destination.label}</span>
                        </div>
                    </div>
                    {aiPrompt ? (
                        <Tooltip title={aiPromptTruncated ? aiPrompt : undefined}>
                            <div className="text-sm text-muted italic">{`"${aiPromptPreview}"`}</div>
                        </Tooltip>
                    ) : null}
                    {subscription.resource_type === SubscriptionResourceTypes.Insight && subscription.resource_name ? (
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
                    <div className="flex items-center justify-between gap-3 min-h-5 whitespace-nowrap">
                        {enabled && subscription.next_delivery_date && (
                            <div className="text-xs text-secondary shrink-0">
                                Next delivery:{' '}
                                <TZLabel
                                    time={subscription.next_delivery_date}
                                    formatDate="ddd, MMM D"
                                    formatTime="HH:mm"
                                    timestampStyle="absolute"
                                />
                            </div>
                        )}
                        {subscription.created_by ? (
                            <div className="flex items-center gap-1 text-xs text-tertiary ml-auto opacity-60 min-w-0 overflow-hidden">
                                <span>Created by</span>
                                <ProfilePicture user={subscription.created_by} size="xs" showName />
                            </div>
                        ) : null}
                    </div>
                </div>
            </div>
        </LemonButton>
    )
}
