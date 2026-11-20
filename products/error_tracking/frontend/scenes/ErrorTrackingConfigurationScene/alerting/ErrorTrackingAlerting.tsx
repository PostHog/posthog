import { BindLogic, useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { AlertWizard } from 'lib/components/Alerting/AlertWizard/AlertWizard'
import {
    AlertCreationView,
    AlertWizardLogicProps,
    alertWizardLogic,
} from 'lib/components/Alerting/AlertWizard/alertWizardLogic'
import { QuillAlertWizard } from 'lib/components/Alerting/AlertWizard/QuillAlertWizard'
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

const HOG_FUNCTION_FILTER_LIST = ERROR_TRACKING_SUB_TEMPLATE_IDS.map((id) => getFiltersFromSubTemplateId(id)).filter(
    (f) => !!f
) as CyclotronJobFiltersType[]

export function ErrorTrackingAlerting(): JSX.Element {
    const wizardProps: AlertWizardLogicProps = {
        logicKey: 'error-tracking',
        subTemplateIds: ERROR_TRACKING_SUB_TEMPLATE_IDS,
        triggers: ERROR_TRACKING_TRIGGERS,
        destinations: ERROR_TRACKING_DESTINATIONS,
        contextId: 'error-tracking',
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
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const cancelTraditionalCreation = (): void => setAlertCreationView(AlertCreationView.None)

    const startWizardCreation = (): void => {
        posthog.capture('error_tracking_alert_creation_started', {
            ui_source: 'wizard_button',
        })
        setAlertCreationView(AlertCreationView.Wizard)
    }

    const cancelWizard = (): void => {
        setAlertCreationView(AlertCreationView.None)
        resetWizard()
    }

    const switchToTraditional = (): void => {
        posthog.capture('error_tracking_alert_creation_switched_to_traditional', {
            ui_source: 'wizard',
        })
        setAlertCreationView(AlertCreationView.Traditional)
        resetWizard()
    }

    if (alertCreationView === AlertCreationView.Wizard) {
        return todayRailNav ? (
            <QuillAlertWizard onCancel={cancelWizard} onSwitchToTraditional={switchToTraditional} />
        ) : (
            <AlertWizard onCancel={cancelWizard} onSwitchToTraditional={switchToTraditional} />
        )
    }

    if (alertCreationView === AlertCreationView.Traditional) {
        return (
            <HogFunctionTemplateList
                type="destination"
                subTemplateIds={subTemplateIds}
                getConfigurationOverrides={(id, subTemplate) =>
                    id ? { filters: getFiltersFromSubTemplateId(id, subTemplate) } : undefined
                }
                extraControls={
                    todayRailNav ? (
                        <Button variant="outline" onClick={cancelTraditionalCreation}>
                            Cancel
                        </Button>
                    ) : (
                        <LemonButton type="secondary" size="small" onClick={cancelTraditionalCreation}>
                            Cancel
                        </LemonButton>
                    )
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
                todayRailNav ? (
                    <Button variant="primary" onClick={startWizardCreation}>
                        New notification
                    </Button>
                ) : (
                    <LemonButton type="primary" size="small" onClick={startWizardCreation}>
                        New notification
                    </LemonButton>
                )
            }
        />
    )
}
