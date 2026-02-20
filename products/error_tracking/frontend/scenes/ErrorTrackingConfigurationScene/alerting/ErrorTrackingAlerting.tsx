import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { HogFunctionTemplateList } from 'scenes/hog-functions/list/HogFunctionTemplateList'
import { HogFunctionList } from 'scenes/hog-functions/list/HogFunctionsList'
import { getFiltersFromSubTemplateId } from 'scenes/hog-functions/list/LinkedHogFunctions'
import { hogFunctionsListLogic } from 'scenes/hog-functions/list/hogFunctionsListLogic'

import { CyclotronJobFiltersType, HogFunctionSubTemplateIdType } from '~/types'

import { ErrorTrackingAlertWizard } from './ErrorTrackingAlertWizard'
import { errorTrackingAlertWizardLogic } from './errorTrackingAlertWizardLogic'

type NewView = 'none' | 'wizard' | 'traditional'

const SUB_TEMPLATE_IDS: HogFunctionSubTemplateIdType[] = [
    'error-tracking-issue-created',
    'error-tracking-issue-reopened',
    'error-tracking-issue-spiking',
]

export function ErrorTrackingAlerting(): JSX.Element {
    const [newView, setNewView] = useState<NewView>('none')

    const hogFunctionFilterList = useMemo(
        () => SUB_TEMPLATE_IDS.map(getFiltersFromSubTemplateId).filter((f) => !!f) as CyclotronJobFiltersType[],
        []
    )

    const logicKey = useMemo(() => {
        return JSON.stringify({ type: 'internal_destination', subTemplateIds: SUB_TEMPLATE_IDS })
    }, [])

    const listLogicProps = useMemo(
        () => ({
            type: 'internal_destination' as const,
            forceFilterGroups: hogFunctionFilterList,
        }),
        [hogFunctionFilterList]
    )

    const { alertCreated } = useValues(errorTrackingAlertWizardLogic)
    const { resetWizard } = useActions(errorTrackingAlertWizardLogic)
    const { loadHogFunctions } = useActions(hogFunctionsListLogic(listLogicProps))

    useEffect(() => {
        if (alertCreated) {
            setNewView('none')
            resetWizard()
            loadHogFunctions()
        }
    }, [alertCreated])

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
            key={logicKey}
            forceFilterGroups={hogFunctionFilterList}
            type="internal_destination"
            extraControls={
                <LemonButton type="primary" size="small" onClick={() => setNewView('wizard')}>
                    New notification
                </LemonButton>
            }
        />
    )
}
