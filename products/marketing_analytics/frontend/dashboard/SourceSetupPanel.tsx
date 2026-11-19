import { useActions, useValues } from 'kea'
import type { ReactNode } from 'react'

import * as moneyPng from '@posthog/brand/hoggies/png/money'
import { IconCheckCircle, IconInfo } from '@posthog/icons'
import { LemonButton, LemonCard, LemonCollapse, LemonTag, Spinner } from '@posthog/lemon-ui'

import { pngHoggie } from 'lib/brand/hoggies'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import type { Suggestion } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/setupPlanLogic'
import { nativeSourceDisplayLabel } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/utils'

import { SourceIcon } from 'products/data_warehouse/frontend/shared/components/SourceIcon'

import { expandedSourceTypes, sourceConnectionGroupsLogic } from './sourceConnectionGroupsLogic'

const HedgehogMoney = pngHoggie(moneyPng)

type SourceConnectionStatus = 'Connected' | 'Syncing' | 'Needs attention' | 'Sync failed'

const needsAction = (status: SourceConnectionStatus): boolean =>
    status === 'Needs attention' || status === 'Sync failed'

export interface SourceSetupPanelProps {
    state: 'checking' | 'scanning' | 'suggestions' | 'empty' | 'error' | 'waiting' | 'dismissed'
    suggestions?: Suggestion[]
    connections?: {
        id: string
        name: string
        sourceType: string
        status: SourceConnectionStatus
        detail: string
        manageUrl?: string
        action?: ReactNode
    }[]
    manageSourceDataAttr?: string
    expansionKey?: string
    compact?: boolean
    title?: string
    description?: string
    showIllustration?: boolean
    footer?: ReactNode
    headerAction?: ReactNode
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
    manageSourceDataAttr = 'marketing-connection-manage-source',
    expansionKey = 'setup',
    footer,
    headerAction,
    compact = false,
    title: titleOverride,
    description: descriptionOverride,
    showIllustration = true,
    onRetry,
    rescanLoading = false,
    rescanDisabledReason,
    onDismiss,
    onRestore,
}: SourceSetupPanelProps): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const sourceTypes = Array.from(new Set(connections.map((connection) => connection.sourceType)))
    const sourceTypesNeedingAction = Array.from(
        new Set(
            connections
                .filter((connection) => needsAction(connection.status))
                .map((connection) => connection.sourceType)
        )
    )
    const groupsLogic = sourceConnectionGroupsLogic({ expansionKey })
    const { expansion } = useValues(groupsLogic)
    const expandedGroups = expandedSourceTypes(expansion, sourceTypes, sourceTypesNeedingAction)
    const { setExpandedSourceTypes } = useActions(groupsLogic)
    const hasConnectionsToFix = connections.some((connection) => needsAction(connection.status))
    const busy = state === 'checking' || state === 'scanning'
    const title =
        titleOverride ??
        (state === 'checking'
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
                      ? hasConnectionsToFix
                          ? 'Some connections need attention'
                          : 'Your connections are getting ready'
                      : 'Connect your ad platforms')
    const description =
        descriptionOverride ??
        (state === 'checking'
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
                      ? hasConnectionsToFix
                          ? 'Check the connections below to finish setting up your spend data.'
                          : 'Spend and ad performance will appear after the first sync finishes. You can connect other platforms while you wait.'
                      : `We found campaign tracking from ${suggestions.length} ${suggestions.length === 1 ? 'platform' : 'platforms'} in your latest event scan.`)

    const rescanButton =
        !busy && onRetry ? (
            <LemonButton
                type="secondary"
                onClick={onRetry}
                loading={rescanLoading}
                disabledReason={rescanDisabledReason}
                data-attr="marketing-onboarding-rescan"
            >
                {state === 'error' ? 'Try again' : 'Scan again'}
            </LemonButton>
        ) : null

    return (
        <LemonCard hoverEffect={false} className="w-full mt-6 p-0 overflow-hidden">
            <div className={compact ? 'p-4 space-y-3' : 'p-6 space-y-5'}>
                {!compact && (state === 'scanning' || state === 'suggestions') && (
                    <LemonTag type="muted">7-day event scan</LemonTag>
                )}
                <div className="flex items-start gap-4" role={busy ? 'status' : undefined}>
                    {busy ? <Spinner className="mt-1 shrink-0" /> : null}
                    <div className="min-w-0 flex-1">
                        <h3 className={compact ? 'text-base mb-1' : 'mb-2'}>{title}</h3>
                        <p className="text-secondary mb-0 max-w-xl">{description}</p>
                    </div>
                    {!busy && showIllustration && (
                        <HedgehogMoney className={compact ? 'w-12 shrink-0' : 'w-20 shrink-0'} />
                    )}
                    {headerAction}
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
                    <LemonCollapse
                        embedded
                        multiple
                        activeKeys={expandedGroups}
                        onChange={(expanded) => setExpandedSourceTypes(expanded, sourceTypes)}
                        panels={sourceTypes.map((sourceType) => {
                            const group = connections.filter((connection) => connection.sourceType === sourceType)
                            return {
                                key: sourceType,
                                header: {
                                    className: 'focus-visible:-outline-offset-2',
                                    children: (
                                        <span className="flex flex-wrap items-center gap-2 min-w-0">
                                            <SourceIcon type={sourceType} size="small" disableTooltip />
                                            <strong>{nativeSourceDisplayLabel(sourceType)}</strong>
                                            <span className="text-secondary">{`${group.length} ${group.length === 1 ? 'connection' : 'connections'}`}</span>
                                        </span>
                                    ),
                                },
                                content: (
                                    <div className="divide-y">
                                        {group.map((connection) => (
                                            <div
                                                key={connection.id}
                                                className="flex flex-wrap items-start justify-between gap-3 py-3"
                                            >
                                                <div className="min-w-0 flex-1 basis-64 space-y-2 break-words">
                                                    <div className="flex items-center flex-wrap gap-2">
                                                        <strong className="break-all">{connection.name}</strong>
                                                        <LemonTag
                                                            type={
                                                                connection.status === 'Sync failed'
                                                                    ? 'danger'
                                                                    : connection.status === 'Needs attention'
                                                                      ? 'warning'
                                                                      : 'info'
                                                            }
                                                        >
                                                            {connection.status}
                                                        </LemonTag>
                                                    </div>
                                                    <p className="text-secondary text-sm mb-0 whitespace-pre-line">
                                                        {connection.detail}
                                                    </p>
                                                </div>
                                                {connection.action ? (
                                                    <div className="shrink-0 ml-auto">{connection.action}</div>
                                                ) : needsAction(connection.status) ? (
                                                    <div className="shrink-0 ml-auto">
                                                        <LemonButton
                                                            type="secondary"
                                                            size="small"
                                                            to={
                                                                connection.manageUrl ??
                                                                urls.dataWarehouseSource(`managed-${connection.id}`)
                                                            }
                                                            targetBlank
                                                            data-attr={manageSourceDataAttr}
                                                        >
                                                            Manage source
                                                        </LemonButton>
                                                    </div>
                                                ) : null}
                                            </div>
                                        ))}
                                    </div>
                                ),
                            }
                        })}
                    />
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
                {!compact && rescanButton}
                {!busy && rescanDisabledReason && <p className="text-secondary text-xs mb-0">{rescanDisabledReason}</p>}
                {!busy && !compact && state !== 'error' && state !== 'waiting' && (
                    <div className="flex items-start gap-2 text-secondary text-sm">
                        <IconInfo className="shrink-0 mt-0.5" />
                        <span>Spend data appears after the first sync finishes.</span>
                    </div>
                )}
                {state === 'waiting' && connections.some((connection) => !needsAction(connection.status)) && (
                    <div className="flex items-start gap-2 text-secondary text-sm">
                        <IconCheckCircle className="shrink-0 mt-0.5" />
                        <span>You can leave this page. Your import will continue in the background.</span>
                    </div>
                )}
            </div>
            {(footer || (compact && rescanButton)) && (
                <div className="border-t p-4 flex flex-wrap items-center justify-between gap-3 bg-bg-light">
                    {footer}
                    {compact && rescanButton}
                </div>
            )}
        </LemonCard>
    )
}
