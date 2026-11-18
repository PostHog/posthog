import { useValues } from 'kea'

import { LemonButton, LemonMenu, LemonMenuItem, LemonMenuItems } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { serviceViewerUrl } from 'products/logs/frontend/components/LogsServices/serviceViewerUrl'
import { tracingUrlForService } from 'products/tracing/frontend/traceLinks'

import { metricsViewerLogic } from './metricsViewerLogic'

/**
 * The metric -> logs / traces pivot.
 *
 * Both destinations inherit the chart's service scope and time window, so the jump lands on the
 * same slice of the same incident. Where the metric carries exemplars there is an exact
 * metric -> trace link already (the chart's markers and the Samples tab); this covers the case
 * where all you have is a service and a window.
 */
export function MetricsRelatedMenu(): JSX.Element {
    const { correlationServices, dateFrom, dateTo } = useValues(metricsViewerLogic)

    const logsDisabledReason = getAccessControlDisabledReason(AccessControlResourceType.Logs, AccessControlLevel.Viewer)
    const tracingDisabledReason = getAccessControlDisabledReason(
        AccessControlResourceType.Tracing,
        AccessControlLevel.Viewer
    )

    const dateRange = { date_from: dateFrom, date_to: dateTo }

    const itemsForService = (serviceName: string): LemonMenuItem[] => [
        {
            label: 'Logs',
            to: serviceViewerUrl(serviceName, { dateRange }),
            disabledReason: logsDisabledReason,
        },
        {
            label: 'Error logs',
            to: serviceViewerUrl(serviceName, { dateRange, severityLevels: ['error'] }),
            disabledReason: logsDisabledReason,
        },
        {
            label: 'Traces',
            to: tracingUrlForService(serviceName, { dateRange }),
            disabledReason: tracingDisabledReason,
        },
    ]

    // One service reads better as a flat list; several need naming, or the items are ambiguous.
    const items: LemonMenuItems =
        correlationServices.length === 1
            ? itemsForService(correlationServices[0])
            : correlationServices.map((serviceName) => ({
                  title: serviceName,
                  items: itemsForService(serviceName),
              }))

    if (!correlationServices.length) {
        return (
            <LemonButton
                size="small"
                type="secondary"
                disabledReason="Filter or group by a service to jump to its logs and traces"
                data-attr="metrics-viewer-related"
            >
                Related
            </LemonButton>
        )
    }

    return (
        <LemonMenu items={items}>
            <LemonButton size="small" type="secondary" data-attr="metrics-viewer-related">
                Related
            </LemonButton>
        </LemonMenu>
    )
}
