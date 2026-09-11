import { useActions, useValues } from 'kea'
import { ReactNode, useEffect } from 'react'

import { LemonBanner, LemonButton, LemonCard, LemonSwitch, Spinner } from '@posthog/lemon-ui'

import { formatPropertyLabel } from 'lib/components/PropertyFilters/utils'
import { TZLabel } from 'lib/components/TZLabel'
import { IconSlack } from 'lib/lemon-ui/icons'
import { cn } from 'lib/utils/css-classes'

import { AnyPropertyFilter } from '~/types'

import { ErrorTrackingAlertApi, ErrorTrackingAlertDestinationApi } from '../../../../generated/api.schemas'
import { errorTrackingEditAccessDisabledReason } from '../../../../utils'
import { THROTTLE_OPTIONS, TRIGGER_OPTIONS, hasEveryTrigger, nativeAlertEditorLogic } from './nativeAlertEditorLogic'
import { nativeAlertsLogic } from './nativeAlertsLogic'

function throttleLabel(seconds: number): string {
    return THROTTLE_OPTIONS.find((option) => option.value === seconds)?.label ?? `Once every ${seconds}s`
}

function triggersLabel(triggers: ErrorTrackingAlertApi['triggers']): string {
    if (hasEveryTrigger(triggers)) {
        return 'Anything happens to a matching issue'
    }
    const labels = TRIGGER_OPTIONS.filter((option) => triggers.includes(option.value)).map((option) => option.label)
    return labels.length > 0 ? labels.join(', ') : 'Never'
}

function DeliveryHealth({ destinations }: { destinations: ErrorTrackingAlertDestinationApi[] }): JSX.Element | null {
    const failing = destinations.find((destination) => destination.consecutive_failures > 0)
    if (failing) {
        return (
            <span className="flex items-center gap-1.5 text-xs text-danger min-w-0">
                <span className="w-2 h-2 rounded-full bg-danger shrink-0" />
                <span className="truncate">Failing: {failing.last_error || 'delivery error'}</span>
            </span>
        )
    }
    const lastDelivered = destinations
        .map((destination) => destination.last_delivered_at)
        .filter((value): value is string => !!value)
        .sort()
        .at(-1)
    if (lastDelivered) {
        return (
            <span className="flex items-center gap-1.5 text-xs text-secondary">
                <span className="w-2 h-2 rounded-full bg-success shrink-0" />
                <span>
                    Delivered <TZLabel time={lastDelivered} />
                </span>
            </span>
        )
    }
    return null
}

function Fact({ label, children }: { label: string; children: ReactNode }): JSX.Element {
    return (
        <span className="flex items-baseline gap-1.5 min-w-0">
            <span className="text-xs text-secondary shrink-0">{label}</span>
            <span className="text-sm truncate">{children}</span>
        </span>
    )
}

function AlertCard({ alert }: { alert: ErrorTrackingAlertApi }): JSX.Element {
    const { alertsLoading } = useValues(nativeAlertsLogic)
    const { setAlertEnabled } = useActions(nativeAlertsLogic)
    const { openEditor } = useActions(nativeAlertEditorLogic)
    const editDisabledReason = errorTrackingEditAccessDisabledReason() ?? undefined
    const properties = (alert.filters.properties ?? []) as AnyPropertyFilter[]
    // Event filters can be set through the API but not in this editor; say they exist rather than hide them.
    const eventFilterCount = alert.filters.events?.length ?? 0
    const filterLabels = properties.map((property) => formatPropertyLabel(property, {}).trim())
    if (eventFilterCount > 0) {
        filterLabels.push(`${eventFilterCount} event ${eventFilterCount === 1 ? 'filter' : 'filters'} set via the API`)
    }

    return (
        <LemonCard
            hoverEffect={!editDisabledReason}
            onClick={editDisabledReason ? undefined : () => openEditor(alert)}
            className={cn('group flex flex-col gap-2 px-3 py-2.5', !alert.enabled && 'opacity-70')}
            data-attr="error-tracking-alert-card"
        >
            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2 min-w-0">
                    {/* The switch lives inside the clickable card; its click must not open the editor. */}
                    <span onClick={(event) => event.stopPropagation()}>
                        <LemonSwitch
                            checked={alert.enabled}
                            onChange={(enabled) => setAlertEnabled({ alert, enabled })}
                            disabledReason={editDisabledReason ?? (alertsLoading ? 'Updating' : undefined)}
                            size="small"
                        />
                    </span>
                    <span className="font-semibold truncate">{alert.name}</span>
                    <DeliveryHealth destinations={alert.destinations} />
                </div>
                <div className="flex items-center gap-2 shrink-0">
                    <span className="text-xs text-secondary">{throttleLabel(alert.throttle_seconds)}</span>
                    <LemonButton
                        size="xsmall"
                        type="tertiary"
                        className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100"
                        onClick={(event) => {
                            event.stopPropagation()
                            openEditor(alert)
                        }}
                        disabledReason={editDisabledReason}
                    >
                        Edit
                    </LemonButton>
                </div>
            </div>
            <div className="flex flex-wrap gap-x-5 gap-y-1 pl-9">
                <Fact label="when">{triggersLabel(alert.triggers)}</Fact>
                <Fact label="if">{filterLabels.length > 0 ? filterLabels.join(', ') : 'Every matching issue'}</Fact>
                <Fact label="to">
                    <span className="inline-flex flex-wrap items-center gap-x-3 gap-y-1">
                        {alert.destinations.map((destination) => (
                            <span
                                key={destination.id}
                                className={cn(
                                    'inline-flex items-center gap-1',
                                    destination.consecutive_failures > 0 && 'text-danger'
                                )}
                            >
                                <IconSlack className="w-3.5 h-3.5 shrink-0" />
                                {destination.config.channel_name || destination.config.channel}
                            </span>
                        ))}
                    </span>
                </Fact>
            </div>
        </LemonCard>
    )
}

export function NativeAlertsList(): JSX.Element {
    const { alerts, alertsLoading, alertsLoaded, loadError } = useValues(nativeAlertsLogic)
    const { loadAlerts } = useActions(nativeAlertsLogic)
    const { openEditor } = useActions(nativeAlertEditorLogic)

    useEffect(() => {
        loadAlerts()
    }, [loadAlerts])

    return (
        <div className="flex flex-col gap-2 @container">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <span className="font-semibold">{alerts.length}</span>
                    <span className="text-secondary">{alerts.length === 1 ? 'alert' : 'alerts'}</span>
                    {alertsLoading && !alertsLoaded && <Spinner />}
                </div>
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => openEditor()}
                    disabledReason={errorTrackingEditAccessDisabledReason() ?? undefined}
                    data-attr="error-tracking-new-alert"
                >
                    New alert
                </LemonButton>
            </div>
            {loadError ? (
                <LemonBanner type="error" action={{ children: 'Retry', onClick: loadAlerts }}>
                    {loadError}
                </LemonBanner>
            ) : alertsLoaded && alerts.length === 0 ? (
                <LemonCard hoverEffect={false} className="text-secondary text-sm">
                    No alerts yet. An alert opens one Slack thread per issue and keeps it updated as the issue changes.
                </LemonCard>
            ) : (
                alerts.map((alert) => <AlertCard key={alert.id} alert={alert} />)
            )}
        </div>
    )
}
