import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'

import { AlertWizard } from 'scenes/hog-functions/AlertWizard/AlertWizard'
import {
    AlertCreationView,
    AlertWizardLogicProps,
    alertWizardLogic,
} from 'scenes/hog-functions/AlertWizard/alertWizardLogic'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'

import { CyclotronJobFiltersType } from '~/types'

import {
    ERROR_TRACKING_DESTINATIONS,
    ERROR_TRACKING_SUB_TEMPLATE_IDS,
    ERROR_TRACKING_TRIGGERS,
} from './alertWizardConfig'

const HOG_FUNCTION_FILTER_LIST = ERROR_TRACKING_SUB_TEMPLATE_IDS.map(getFiltersFromSubTemplateId).filter(
    (f) => !!f
) as CyclotronJobFiltersType[]

export function ErrorTrackingAlerting(): JSX.Element {
    const wizardProps: AlertWizardLogicProps = {
        logicKey: 'error-tracking',
        subTemplateIds: ERROR_TRACKING_SUB_TEMPLATE_IDS,
        triggers: ERROR_TRACKING_TRIGGERS,
        destinations: ERROR_TRACKING_DESTINATIONS,
    }

    return (
        <BindLogic logic={alertWizardLogic} props={wizardProps}>
            <ErrorTrackingAlertingInner />
        </BindLogic>
    )
}

function ErrorTrackingAlertingInner(): JSX.Element {
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
                getConfigurationOverrides={(id) => (id ? getFiltersFromSubTemplateId(id) : undefined)}
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
