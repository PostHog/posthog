import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'

import { CyclotronJobFiltersType } from '~/types'

import { ErrorTrackingAlertWizard } from './ErrorTrackingAlertWizard'
import { SUB_TEMPLATE_IDS, errorTrackingAlertWizardLogic } from './errorTrackingAlertWizardLogic'

const HOG_FUNCTION_FILTER_LIST = SUB_TEMPLATE_IDS.map(getFiltersFromSubTemplateId).filter(
    (f) => !!f
) as CyclotronJobFiltersType[]

export function ErrorTrackingAlerting(): JSX.Element {
    const { alertCreationView } = useValues(errorTrackingAlertWizardLogic)
    const { setAlertCreationView, resetWizard } = useActions(errorTrackingAlertWizardLogic)

    if (alertCreationView === 'wizard') {
        return (
            <ErrorTrackingAlertWizard
                onCancel={() => {
                    setAlertCreationView('none')
                    resetWizard()
                }}
                onSwitchToTraditional={() => {
                    setAlertCreationView('traditional')
                    resetWizard()
                }}
            />
        )
    }

    if (alertCreationView === 'traditional') {
        return (
            <HogFunctionTemplateList
                type="destination"
                subTemplateIds={SUB_TEMPLATE_IDS}
                getConfigurationOverrides={(id) => (id ? getFiltersFromSubTemplateId(id) : undefined)}
                extraControls={
                    <LemonButton type="secondary" size="small" onClick={() => setAlertCreationView('none')}>
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
                <LemonButton type="primary" size="small" onClick={() => setAlertCreationView('wizard')}>
                    New notification
                </LemonButton>
            }
        />
    )
}
