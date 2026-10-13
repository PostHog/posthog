import { useValues } from 'kea'

import type { WizardRunApi } from '../generated/api.schemas'
import { wizardRunDetailsLogic } from '../wizardRunDetailsLogic'
import { WizardRunDetailsDialog } from './WizardRunDetailsDialog'
import { wizardRunSyncLogic } from './wizardRunSyncLogic'

export function WizardRunSceneSyncDetailsDialog({
    projectId,
    onRunAgain,
}: {
    projectId: string
    onRunAgain: (run: WizardRunApi) => void
}): JSX.Element {
    const { run, tasks } = useValues(wizardRunSyncLogic({ projectId }))
    const { selectedRun } = useValues(wizardRunDetailsLogic)

    return <WizardRunDetailsDialog tasks={selectedRun?.id === run?.id ? tasks : []} onRunAgain={onRunAgain} />
}
