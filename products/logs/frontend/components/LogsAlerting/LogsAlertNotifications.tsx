import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { AlertNotificationDestinationView } from 'products/alerts/frontend/components/AlertNotificationDestinationEditor'
import { AlertDestinationEntry } from 'products/alerts_platform/frontend/destinations/platformAlertDestinations'
import { PlatformAlertNotifications } from 'products/alerts_platform/frontend/destinations/PlatformAlertNotifications'

import { LOGS_ALERT_DESTINATION_TYPE_OPTIONS, logsAlertDestinationsLogicProps } from './logsAlertDestinations'
import { CUSTOM_MESSAGE_TAG } from './logsAlertUtils'

export function LogsAlertNotifications({ alertId }: { alertId?: string }): JSX.Element {
    const { featureFlags } = useValues(featureFlagLogic)
    const customization = !!featureFlags[FEATURE_FLAGS.ALERTS_DESTINATION_CUSTOMIZATION]

    const destinationView = (destination: AlertDestinationEntry): Partial<AlertNotificationDestinationView> => {
        // The detail page opens a destination by any one of its HogFunctions.
        const hogFunctionId = destination.hog_function_ids?.[0]
        const detailUrl =
            alertId && hogFunctionId ? urls.logsAlertNotificationDetail(alertId, hogFunctionId) : undefined
        return {
            tags: [
                {
                    label: destination.enabled ? 'Active' : 'Paused',
                    type: destination.enabled ? 'success' : 'default',
                },
                ...(customization && destination.message_customized ? [CUSTOM_MESSAGE_TAG] : []),
            ],
            viewAction: {
                kind: 'button',
                label: 'View',
                url: detailUrl,
                disabledReason: detailUrl ? undefined : 'This destination has no message to view',
                dataAttr: 'logs-alert-destination-view',
            },
        }
    }

    return (
        <PlatformAlertNotifications
            {...logsAlertDestinationsLogicProps(alertId)}
            typeOptions={LOGS_ALERT_DESTINATION_TYPE_OPTIONS}
            destinationView={destinationView}
        />
    )
}
