import { useActions, useValues } from 'kea'

import { IconBell } from '@posthog/icons'
import { LemonBanner, LemonInputSelect } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

import {
    TriggerFrequencyOption,
    registerTriggerType,
} from 'products/workflows/frontend/Workflows/hogflows/registry/triggers/triggerTypeRegistry'
import { workflowLogic } from 'products/workflows/frontend/Workflows/workflowLogic'

import {
    INSIGHT_ALERT_FIRING_EVENT,
    InternalEventInsightAlertTriggerConfig,
    decodeInsightAlertFilters,
    encodeInsightAlertFilters,
    isInsightAlertTriggerConfig,
} from './insightAlertTriggerFilters'
import { insightAlertTriggerOptionsLogic } from './insightAlertTriggerOptionsLogic'

const CALENDAR_DAY_TTL = 24 * 60 * 60

// A flapping alert notifies on every check it breaches, so these key the masking on the alert, not on a person.
const INSIGHT_ALERT_FREQUENCY_OPTIONS: TriggerFrequencyOption[] = [
    { value: null, label: 'Every time the alert notifies' },
    {
        value: "{concat(event.properties.alert_id, '-', formatDateTime(now(), '%Y-%m-%d'))}",
        label: 'Once per alert per calendar day',
        fixedTtl: CALENDAR_DAY_TTL,
    },
]

function StepTriggerConfigurationInsightAlert({ node }: { node: any }): JSX.Element {
    const { setWorkflowActionConfig } = useActions(workflowLogic)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const { alerts, alertsLoading } = useValues(insightAlertTriggerOptionsLogic)
    const { loadAlerts } = useActions(insightAlertTriggerOptionsLogic)

    const config = node.data.config as InternalEventInsightAlertTriggerConfig
    const filters = decodeInsightAlertFilters(config.filters?.properties)
    const validationResult = actionValidationErrorsById[node.data.id]

    const update = (alertIds: string[]): void => {
        setWorkflowActionConfig(node.data.id, {
            type: 'internal-event',
            filters: {
                source: 'internal-events',
                events: [{ id: INSIGHT_ALERT_FIRING_EVENT, type: 'events' }],
                properties: encodeInsightAlertFilters({ ...filters, alertIds }),
            },
        })
    }

    if (alerts === null) {
        return alertsLoading ? (
            <p className="mb-0 text-sm text-muted-alt">Loading alerts…</p>
        ) : (
            <LemonBanner type="error" className="w-full" action={{ children: 'Try again', onClick: () => loadAlerts() }}>
                Couldn't load your alerts. Try again, and if it keeps happening contact support.
            </LemonBanner>
        )
    }

    if (alerts.length === 0 && filters.alertIds.length === 0) {
        return (
            <LemonBanner type="info" className="w-full">
                <p className="mb-0">
                    This trigger needs an alert on an insight you can view, and there isn't one yet. Create an alert on
                    an insight, then come back and pick it.{' '}
                    <Link to={urls.alerts()} className="font-semibold">
                        Go to alerts
                    </Link>
                </p>
            </LemonBanner>
        )
    }

    const known = new Set(alerts.map((alert) => alert.id))
    const options = [
        ...alerts.map((alert) => ({
            key: alert.id,
            label: alert.name || 'Unnamed alert',
            tooltip: alert.insight_display_name ? `On ${alert.insight_display_name}` : undefined,
        })),
        // An alert someone else picked, on an insight you can't view, stays selectable so a save keeps it.
        ...filters.alertIds.filter((id) => !known.has(id)).map((id) => ({ key: id, label: id })),
    ]

    return (
        <div className="flex flex-col gap-2 w-full">
            <p className="mb-0 text-sm text-muted-alt">
                This workflow runs each time a picked alert sends a notification. When an alert waits for its
                investigation before it notifies, the run starts when the notification goes out. Runs have no associated
                person, so person-dependent steps are unavailable.
            </p>

            <LemonField.Pure
                label="Alerts"
                error={validationResult?.errors?.alertIds}
                info="Only alerts on insights you can view are listed."
            >
                <LemonInputSelect
                    mode="multiple"
                    value={filters.alertIds}
                    options={options}
                    placeholder="Select the alerts to listen for"
                    onChange={update}
                    data-attr="insight-alert-trigger-alerts"
                />
            </LemonField.Pure>

            <p className="mb-0 text-xs text-muted-alt">
                Steps can use the alert's details, such as <code>{'{event.properties.alert_name}'}</code>,{' '}
                <code>{'{event.properties.insight_name}'}</code>, <code>{'{event.properties.insight_id}'}</code>,{' '}
                <code>{'{event.properties.state}'}</code> and <code>{'{event.properties.breaches}'}</code>.
            </p>
        </div>
    )
}

registerTriggerType({
    // The tile's own identity, not the stored config type: `internal-event` carries every internal
    // event, so naming the tile after it would make this tile claim all of them.
    value: 'insight-alert',
    label: 'Insight alert',
    icon: <IconBell />,
    description: 'Trigger when an insight alert sends a notification',
    group: 'Alerts',
    matchConfig: (config) => isInsightAlertTriggerConfig(config),
    buildConfig: () => ({
        type: 'internal-event',
        filters: {
            source: 'internal-events',
            events: [{ id: INSIGHT_ALERT_FIRING_EVENT, type: 'events' }],
            properties: [],
        },
    }),
    validate: (config): { valid: boolean; errors: Record<string, string> } | null => {
        if (!isInsightAlertTriggerConfig(config)) {
            return null
        }
        if (!decodeInsightAlertFilters(config.filters?.properties).alertIds.length) {
            return { valid: false, errors: { alertIds: 'Pick at least one alert' } }
        }
        return { valid: true, errors: {} }
    },
    ConfigComponent: StepTriggerConfigurationInsightAlert,
    frequencyOptions: INSIGHT_ALERT_FREQUENCY_OPTIONS,
    frequencyDescription: 'Limit how often each alert can start this workflow',
})
