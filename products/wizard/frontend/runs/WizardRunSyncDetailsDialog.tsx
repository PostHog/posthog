import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import type { WizardRunApi, WizardRunTaskApi } from '../generated/api.schemas'
import { wizardRunDetailsLogic } from '../wizardRunDetailsLogic'
import { WizardRunDetailsDialog } from './WizardRunDetailsDialog'

export function WizardRunSyncDetailsDialog({
    run,
    tasks,
    onClose,
}: {
    run: WizardRunApi
    tasks: readonly WizardRunTaskApi[]
    onClose: () => void
}): JSX.Element {
    useMountedLogic(wizardRunDetailsLogic)
    const { selectRun } = useActions(wizardRunDetailsLogic)

    useEffect(() => {
        selectRun(run)
        return () => selectRun(null)
    }, [run, selectRun])

    return <WizardRunDetailsDialog tasks={tasks} onClose={onClose} />
}
