import { BindLogic, useActions, useValues } from 'kea'

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

import { UPTIME_DESTINATIONS, UPTIME_SUB_TEMPLATE_IDS, UPTIME_TRIGGERS } from './alertWizardConfig'

const HOG_FUNCTION_FILTER_LIST = UPTIME_SUB_TEMPLATE_IDS.map(getFiltersFromSubTemplateId).filter(
    (f) => !!f
) as CyclotronJobFiltersType[]

export function UptimeAlerts(): JSX.Element {
    const wizardProps: AlertWizardLogicProps = {
        logicKey: 'uptime',
        subTemplateIds: UPTIME_SUB_TEMPLATE_IDS,
        triggers: UPTIME_TRIGGERS,
        destinations: UPTIME_DESTINATIONS,
    }

    return (
        <BindLogic logic={alertWizardLogic} props={wizardProps}>
            <UptimeAlertsInner />
        </BindLogic>
    )
}

function UptimeAlertsInner(): JSX.Element {
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
            extraControls={
                <LemonButton type="primary" size="small" onClick={() => setAlertCreationView(AlertCreationView.Wizard)}>
                    New alert
                </LemonButton>
            }
        />
    )
}
