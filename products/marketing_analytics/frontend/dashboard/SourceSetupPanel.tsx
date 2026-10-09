import { useValues } from 'kea'
import type { ReactNode } from 'react'

import * as moneyPng from '@posthog/brand/hoggies/png/money'
import { IconCheckCircle, IconInfo } from '@posthog/icons'
import { LemonButton, LemonCard, LemonCollapse, LemonTag, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

const HedgehogMoney = pngHoggie(moneyPng)

export interface SourceSetupPanelProps {
    state: 'checking' | 'scanning' | 'suggestions' | 'empty' | 'error' | 'waiting' | 'dismissed'
    suggestions?: Suggestion[]
    connections?: {
        id: string
        name: string
        sourceType: string
        status: 'Connected' | 'Syncing' | 'Needs attention'
        detail: string
    }[]
    compact?: boolean
    footer?: ReactNode
    onRetry?: () => void
    rescanLoading?: boolean
    rescanDisabledReason?: string | null
    onDismiss?: (id: string) => void
    onRestore?: () => void
}

export function SourceSetupPanel({
    state,
    suggestions = [],
    connections = [],
    footer,
    compact = false,
    onRetry,
    rescanLoading = false,
    rescanDisabledReason,
    onDismiss,
    onRestore,
}: SourceSetupPanelProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const busy = state === 'checking' || state === 'scanning'
    const title =
        state === 'checking'
            ? 'Checking your connections'
            : state === 'scanning'
              ? 'Finding your ad platforms'
              : state === 'dismissed'
                ? 'Your suggestions are hidden'
                : state === 'empty'
                  ? 'Choose an ad platform'
                  : state === 'error'
                    ? 'Could not check your events'
                    : state === 'waiting'
                      ? connections.some((connection) => connection.status === 'Needs attention')
                          ? 'Some connections need attention'
                          : 'Your connections are getting ready'
                      : 'Connect your ad platforms'
    const description =
        state === 'checking'
            ? 'Looking for connected ad platforms.'
            : state === 'scanning'
              ? 'Checking campaign tracking in events from the last 7 days.'
              : state === 'dismissed'
                ? 'You dismissed the detected platforms. Restore your suggestions or choose an integration manually.'
                : state === 'empty'
                  ? 'No ad platforms were detected in your latest 7-day event scan. You can choose an integration manually to import spend data.'
                  : state === 'error'
                    ? 'Try checking your events again, or choose an integration manually.'
                    : state === 'waiting'
                      ? connections.some((connection) => connection.status === 'Needs attention')
                          ? 'Check the connections below to finish setting up your spend data.'
                          : 'Spend and ad performance will appear after the first sync finishes. You can connect other platforms while you wait.'
                      : `We found campaign tracking from ${suggestions.length} ${suggestions.length === 1 ? 'platform' : 'platforms'} in your latest event scan.`

    return (
        <LemonCard
            hoverEffect={false}
            className={
                compact ? 'w-full mt-6 !p-0 overflow-hidden' : 'max-w-3xl w-full mx-auto mt-6 !p-0 overflow-hidden'
            }
        >
            <div className={compact ? 'p-4 space-y-3' : 'p-6 space-y-5'}>
                {(state === 'scanning' || state === 'suggestions') && (
                    <LemonTag type="muted">7-day event scan</LemonTag>
                )}
                <div className="flex items-start gap-4" role={busy ? 'status' : undefined}>
                    {busy ? <Spinner className="mt-1 shrink-0" /> : null}
                    <div className="min-w-0 flex-1">
                        <h3 className="text-xl mb-2">{title}</h3>
                        <p className="text-secondary mb-0 max-w-xl">{description}</p>
                    </div>
                    {!busy && <HedgehogMoney className={compact ? 'w-12 shrink-0' : 'w-20 shrink-0'} />}
                </div>
                {state === 'empty' && (
                    <p className="text-secondary text-sm mb-4">
                        Make sure your ad links include UTM parameters, such as utm_source and utm_medium, and that
                        PostHog captures them.
                    </p>
                )}
                {!busy && !compact && (
                    <div className="space-y-1">
                        <strong className="text-sm">Your marketing data in one place</strong>
                        <p className="text-secondary text-sm mb-0">
                            Compare campaign performance across your marketing sources. Use PostHog events as conversion
                            goals to measure conversion costs and ROAS.
                        </p>
                        {featureFlags[FEATURE_FLAGS.MARKETING_ANALYTICS_ORGANIC_KEYWORDS] && (
                            <p className="text-secondary text-sm mb-0">
                                Compare paid keywords and organic search queries to optimize your search ads.
                            </p>
                        )}
                    </div>
                )}
                {connections.length > 0 && (
                    <div className="divide-y border-t">
                        {connections.map((connection) => (
                            <div key={connection.id} className="py-4 space-y-2">
                                <div className="flex items-center flex-wrap gap-3">
                                    <SourceIcon type={connection.sourceType} size="small" disableTooltip />
                                    <strong>{connection.name}</strong>
                                    <LemonTag type={connection.status === 'Needs attention' ? 'warning' : 'info'}>
                                        {connection.status}
                                    </LemonTag>
                                </div>
                                <p className="text-secondary text-sm mb-0">{connection.detail}</p>
                                {connection.status === 'Needs attention' && (
                                    <LemonButton
                                        type="secondary"
                                        size="small"
                                        to={urls.dataWarehouseSource(connection.id)}
                                        targetBlank
                                    >
                                        Manage source
                                    </LemonButton>
                                )}
                            </div>
                        ))}
                    </div>
                )}
                {suggestions.length > 0 && !busy && (
                    <div className="divide-y border-t">
                        {suggestions.map((suggestion) => (
                            <div key={suggestion.id} className={compact ? 'py-2' : 'py-4'}>
                                <div className="flex items-center justify-between flex-wrap gap-3">
                                    <div className="flex items-center gap-3 min-w-0">
                                        <SourceIcon
                                            type={suggestion.apply?.kind as string}
                                            size="small"
                                            disableTooltip
                                        />
                                        <div>
                                            <strong>{suggestion.title.replace(/^Connect /, '')}</strong>
                                            <p className="text-secondary text-sm mb-0">
                                                {suggestion.event_volume
                                                    ? `Found in ${suggestion.event_volume} events`
                                                    : 'Found in campaign tracking'}
                                            </p>
                                        </div>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        {suggestion.apply?.op === 'open_source_wizard' &&
                                            typeof suggestion.apply.kind === 'string' &&
                                            suggestion.apply.kind.length > 0 && (
                                                <LemonButton
                                                    type="primary"
                                                    size="small"
                                                    to={urls.dataWarehouseSourceNew(
                                                        suggestion.apply.kind,
                                                        urls.marketingAnalyticsApp(),
                                                        'Marketing analytics'
                                                    )}
                                                    targetBlank
                                                    data-attr="marketing-onboarding-connect-source"
                                                >
                                                    Connect
                                                </LemonButton>
                                            )}
                                        {onDismiss && (
                                            <LemonButton
                                                size="small"
                                                type="tertiary"
                                                onClick={() => onDismiss(suggestion.id)}
                                            >
                                                Dismiss
                                            </LemonButton>
                                        )}
                                    </div>
                                </div>
                                {!compact && (
                                    <LemonCollapse
                                        embedded
                                        size="small"
                                        className="mt-2"
                                        panels={[
                                            {
                                                key: suggestion.id,
                                                header: 'View detection details',
                                                content: (
                                                    <p className="text-secondary text-sm mb-0">{suggestion.evidence}</p>
                                                ),
                                            },
                                        ]}
                                    />
                                )}
                            </div>
                        ))}
                    </div>
                )}
                {state === 'dismissed' && onRestore && (
                    <LemonButton type="secondary" onClick={onRestore}>
                        Restore suggestions
                    </LemonButton>
                )}
                {!busy && onRetry && (
                    <LemonButton
                        type="secondary"
                        onClick={onRetry}
                        loading={rescanLoading}
                        disabledReason={rescanDisabledReason}
                        data-attr="marketing-onboarding-rescan"
                    >
                        {state === 'error' ? 'Try again' : 'Scan again'}
                    </LemonButton>
                )}
                {!busy && rescanDisabledReason && <p className="text-secondary text-xs mb-0">{rescanDisabledReason}</p>}
                {!busy && !compact && state !== 'error' && state !== 'waiting' && (
                    <div className="flex items-start gap-2 text-secondary text-sm">
                        <IconInfo className="shrink-0 mt-0.5" />
                        <span>Spend data appears after the first sync finishes.</span>
                    </div>
                )}
                {state === 'waiting' && connections.some((connection) => connection.status !== 'Needs attention') && (
                    <div className="flex items-start gap-2 text-secondary text-sm">
                        <IconCheckCircle className="shrink-0 mt-0.5" />
                        <span>You can leave this page. Your import will continue in the background.</span>
                    </div>
                )}
            </div>
            {footer && (
                <div className="border-t p-4 flex flex-wrap items-center justify-between gap-3 bg-bg-light">
                    {footer}
                </div>
            )}
        </LemonCard>
    )
}
