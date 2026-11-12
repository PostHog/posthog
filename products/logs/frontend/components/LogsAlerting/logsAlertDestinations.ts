import {
    AlertDestinationsApi,
    DESTINATION_TYPE_OPTIONS,
} from 'products/alerts_platform/frontend/destinations/platformAlertDestinations'
import { PlatformAlertDestinationsLogicProps } from 'products/alerts_platform/frontend/destinations/platformAlertDestinationsLogic'
import { PlatformAlertDestinationTypeEnumApi } from 'products/alerts_platform/frontend/generated/api.schemas'
import {
    logsAlertsDestinationsCreate,
    logsAlertsDestinationsDeleteCreate,
    logsAlertsRetrieve,
} from 'products/logs/frontend/generated/api'
import { LogsAlertCreateDestinationApi } from 'products/logs/frontend/generated/api.schemas'

const LOGS_DESTINATION_TYPES: string[] = [
    PlatformAlertDestinationTypeEnumApi.Slack,
    PlatformAlertDestinationTypeEnumApi.Teams,
    PlatformAlertDestinationTypeEnumApi.Pagerduty,
    PlatformAlertDestinationTypeEnumApi.Webhook,
]

export const LOGS_ALERT_DESTINATION_TYPE_OPTIONS = DESTINATION_TYPE_OPTIONS.filter((option) =>
    LOGS_DESTINATION_TYPES.includes(option.value)
)

// The logs alert routes, which Terraform also uses, keep each destination's HogFunctions beside its platform row.
const LOGS_ALERT_DESTINATIONS_API: AlertDestinationsApi = {
    list: async (projectId, alertId) => {
        const alert = await logsAlertsRetrieve(projectId, alertId)
        return alert.destinations.map((destination) => ({
            ...destination,
            // A destination added before the platform kept one has no id of its own.
            id: destination.id ?? destination.hog_function_ids.join(','),
        }))
    },
    create: (projectId, alertId, { event_kinds: _eventKinds, ...destination }) =>
        logsAlertsDestinationsCreate(projectId, alertId, destination as LogsAlertCreateDestinationApi),
    remove: (projectId, alertId, destination) =>
        logsAlertsDestinationsDeleteCreate(
            projectId,
            alertId,
            destination.hog_function_ids?.length
                ? { hog_function_ids: destination.hog_function_ids }
                : { destination_ids: [destination.id] }
        ),
}

export function logsAlertDestinationsLogicProps(alertId?: string): PlatformAlertDestinationsLogicProps {
    return { alertId, sourceKind: 'logs', api: LOGS_ALERT_DESTINATIONS_API }
}
