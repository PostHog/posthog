import { urls } from 'scenes/urls'

import {
    AlertDestinationsApi,
    DESTINATION_TYPE_OPTIONS,
} from 'products/alerts_platform/frontend/destinations/platformAlertDestinations'
import { PlatformAlertDestinationsLogicProps } from 'products/alerts_platform/frontend/destinations/platformAlertDestinationsLogic'
import {
    logsAlertsDestinationsCreate,
    logsAlertsDestinationsCustomizeCreate,
    logsAlertsDestinationsDeleteCreate,
    logsAlertsDestinationsResetCreate,
    logsAlertsRetrieve,
} from 'products/logs/frontend/generated/api'
import {
    LogsAlertCreateDestinationApi,
    LogsAlertDestinationTypeEnumApi,
} from 'products/logs/frontend/generated/api.schemas'

const LOGS_DESTINATION_TYPES: string[] = Object.values(LogsAlertDestinationTypeEnumApi)

export const LOGS_ALERT_DESTINATION_TYPE_OPTIONS = DESTINATION_TYPE_OPTIONS.filter((option) =>
    LOGS_DESTINATION_TYPES.includes(option.value)
)

// The logs alert routes, which Terraform also uses, keep each destination's HogFunctions beside its platform row.
const LOGS_ALERT_DESTINATIONS_API: AlertDestinationsApi = {
    list: async (projectId, alertId) => {
        const alert = await logsAlertsRetrieve(projectId, alertId)
        return alert.destinations.map((destination) => ({
            ...destination,
            // HogFunction ids while they exist: one row can copy a group that has since split in two.
            id: destination.hog_function_ids.length ? destination.hog_function_ids.join(',') : String(destination.id),
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
    customize: async (projectId, alertId, destination) =>
        (
            await logsAlertsDestinationsCustomizeCreate(
                projectId,
                alertId,
                destination.hog_function_ids?.length
                    ? { hog_function_ids: destination.hog_function_ids }
                    : { destination_id: destination.id }
            )
        ).hog_function_ids,
    reset: (projectId, alertId, destination) =>
        logsAlertsDestinationsResetCreate(projectId, alertId, { hog_function_ids: destination.hog_function_ids ?? [] }),
    messageEditorUrl: (alertId, hogFunctionIds) => urls.logsAlertNotificationDetail(alertId, hogFunctionIds[0]),
}

export function logsAlertDestinationsLogicProps(alertId?: string): PlatformAlertDestinationsLogicProps {
    return { alertId, sourceKind: 'logs', api: LOGS_ALERT_DESTINATIONS_API }
}
