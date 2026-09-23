import { useValues } from 'kea'

import { lemonToast } from '@posthog/lemon-ui'

import { useLocalStorage } from 'lib/hooks/useLocalStorage'
import { projectLogic } from 'scenes/projectLogic'

import { WizardRunSyncProject } from './WizardRunSyncProject'

export function WizardRunSyncFab(): JSX.Element | null {
    const { currentProjectId } = useValues(projectLogic)
    const [hidden, setHidden] = useLocalStorage('wizard-run-sync-hidden', false)

    return currentProjectId && !hidden ? (
        <WizardRunSyncProject
            key={currentProjectId}
            projectId={String(currentProjectId)}
            onHide={() => {
                setHidden(true)
                lemonToast.info('You can still follow runs on the Wizard page.')
            }}
        />
    ) : null
}
