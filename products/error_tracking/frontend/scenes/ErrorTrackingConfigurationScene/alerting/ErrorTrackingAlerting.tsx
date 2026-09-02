import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { AlertWizard } from 'lib/components/Alerting/AlertWizard/AlertWizard'
import {
    AlertCreationView,
    AlertWizardLogicProps,
    alertWizardLogic,
} from 'lib/components/Alerting/AlertWizard/alertWizardLogic'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'

import { CyclotronJobFiltersType } from '~/types'

import {
    ERROR_TRACKING_DESTINATIONS,
    ERROR_TRACKING_SUB_TEMPLATE_IDS,
    ERROR_TRACKING_TRIGGERS,
} from './alertWizardConfig'
import { NativeAlertEditor } from './native/NativeAlertEditor'
import { NativeAlertsList } from './native/NativeAlertsList'

const HOG_FUNCTION_FILTER_LIST = ERROR_TRACKING_SUB_TEMPLATE_IDS.map(getFiltersFromSubTemplateId).filter(
    (f) => !!f
) as CyclotronJobFiltersType[]

export function ErrorTrackingAlerting(): JSX.Element {
    const hasNativeAlerts = useFeatureFlag('ERROR_TRACKING_NATIVE_ALERTS')
    const wizardProps: AlertWizardLogicProps = {
        logicKey: 'error-tracking',
        subTemplateIds: ERROR_TRACKING_SUB_TEMPLATE_IDS,
        triggers: ERROR_TRACKING_TRIGGERS,
        destinations: ERROR_TRACKING_DESTINATIONS,
        contextId: 'error-tracking',
    }

    if (!hasNativeAlerts) {
        return (
            <BindLogic logic={alertWizardLogic} props={wizardProps}>
                <ErrorTrackingNotifications />
            </BindLogic>
        )
    }

    // Native alerts sit above the existing destinations: nothing already configured
    // moves or changes, and non-Slack destinations keep working as they are.
    return (
        <div className="flex flex-col gap-8">
            <section className="flex flex-col gap-2">
                <div>
                    <h3 className="mb-0">Alerts</h3>
                    <p className="text-secondary mb-0">
                        One Slack thread per issue. The thread opens when an issue matches and is kept up to date as the
                        issue changes.
                    </p>
                </div>
                <NativeAlertsList />
                <NativeAlertEditor />
            </section>
            <section className="flex flex-col gap-2">
                <div>
                    <h3 className="mb-0">Notifications</h3>
                    <p className="text-secondary mb-0">
                        Destinations you set up before. Each sends one message per event and keeps working unchanged.
                    </p>
                </div>
                <BindLogic logic={alertWizardLogic} props={wizardProps}>
                    <ErrorTrackingNotifications />
                </BindLogic>
            </section>
        </div>
    )
}

function ErrorTrackingNotifications(): JSX.Element {
    const { alertCreationView, subTemplateIds } = useValues(alertWizardLogic)
    const { setAlertCreationView, resetWizard } = useActions(alertWizardLogic)

    if (alertCreationView === AlertCreationView.Wizard) {
        return (
            <AlertWizard
                onCancel={() => {
                    setAlertCreationView(AlertCreationView.None)
                    resetWizard()
                }}
                onSwitchToTraditional={() => {
                    posthog.capture('error_tracking_alert_creation_switched_to_traditional', {
                        source: 'wizard',
                    })
                    setAlertCreationView(AlertCreationView.Traditional)
                    resetWizard()
                }}
            />
        )
    }

    if (alertCreationView === AlertCreationView.Traditional) {
        return (
            <HogFunctionTemplateList
                type="destination"
                subTemplateIds={subTemplateIds}
                getConfigurationOverrides={(id) => (id ? { filters: getFiltersFromSubTemplateId(id) } : undefined)}
                extraControls={
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => setAlertCreationView(AlertCreationView.None)}
                    >
                        Cancel
                    </LemonButton>
                }
            />
        )
    }

    return (
        <HogFunctionList
            forceFilterGroups={HOG_FUNCTION_FILTER_LIST}
            type="internal_destination"
            onDeleteHogFunction={(hogFunction) => {
                posthog.capture('error_tracking_alert_deleted', {
                    hog_function_id: hogFunction.id,
                })
            }}
            onEditHogFunction={(hogFunction) => {
                posthog.capture('error_tracking_alert_edit_clicked', {
                    hog_function_id: hogFunction.id,
                })
            }}
            extraControls={
                <LemonButton
                    type="primary"
                    size="small"
                    onClick={() => {
                        posthog.capture('error_tracking_alert_creation_started', {
                            source: 'wizard_button',
                        })
                        setAlertCreationView(AlertCreationView.Wizard)
                    }}
                >
                    New notification
                </LemonButton>
            }
        />
    )
}
