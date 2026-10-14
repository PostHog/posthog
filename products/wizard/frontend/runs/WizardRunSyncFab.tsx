import { useValues } from 'kea'

import { projectLogic } from 'scenes/projectLogic'

import { WizardRunSyncProject } from './WizardRunSyncProject'

export function WizardRunSyncFab(): JSX.Element | null {
    const { currentProjectId } = useValues(projectLogic)

    return currentProjectId ? (
        <WizardRunSyncProject key={currentProjectId} projectId={String(currentProjectId)} />
    ) : null
}
