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
    const { newView } = useValues(errorTrackingAlertWizardLogic)
    const { setNewView, resetWizard } = useActions(errorTrackingAlertWizardLogic)

    if (newView === 'wizard') {
        return (
            <ErrorTrackingAlertWizard
                onCancel={() => {
                    setNewView('none')
                    resetWizard()
                }}
                onSwitchToTraditional={() => {
                    setNewView('traditional')
                    resetWizard()
                }}
            />
        )
    }

    if (newView === 'traditional') {
        return (
            <HogFunctionTemplateList
                type="destination"
                subTemplateIds={SUB_TEMPLATE_IDS}
                getConfigurationOverrides={(id) => (id ? getFiltersFromSubTemplateId(id) : undefined)}
                extraControls={
                    <LemonButton type="secondary" size="small" onClick={() => setNewView('none')}>
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
                <LemonButton type="primary" size="small" onClick={() => setNewView('wizard')}>
                    New notification
                </LemonButton>
            }
        />
    )
}
