import { SceneExport } from 'scenes/sceneTypes'

import { ErrorTrackingSetupPrompt } from '../components/ErrorTrackingSetupPrompt/ErrorTrackingSetupPrompt'
import { errorTrackingImpactSceneLogic } from './errorTrackingImpactSceneLogic'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

export const scene: SceneExport = {
    component: ErrorTrackingImpactScene,
    logic: errorTrackingImpactSceneLogic,
}

export function ErrorTrackingImpactScene(): JSX.Element {
    const { issues } = useValues(errorTrackingImpactSceneLogic)
    const { loadIssues } = useActions(errorTrackingImpactSceneLogic)

    useEffect(() => {
        loadIssues()
    }, [loadIssues])

    return (
        <ErrorTrackingSetupPrompt>
            <div>{JSON.stringify(issues)}</div>
        </ErrorTrackingSetupPrompt>
    )
}
