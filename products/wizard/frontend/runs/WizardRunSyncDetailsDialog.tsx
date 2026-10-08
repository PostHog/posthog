import { useActions, useMountedLogic } from 'kea'
import { useEffect } from 'react'

import type { WizardRunApi, WizardRunTaskApi } from '../generated/api.schemas'
import { type WizardRunDetailSource, wizardRunDetailsLogic } from '../wizardRunDetailsLogic'
import { WizardRunDetailsDialog } from './WizardRunDetailsDialog'

export function WizardRunSyncDetailsDialog({
    run,
    tasks,
    source,
    onClose,
}: {
    run: WizardRunApi
    tasks: readonly WizardRunTaskApi[]
    source: WizardRunDetailSource
    onClose: () => void
}): JSX.Element {
    useMountedLogic(wizardRunDetailsLogic)
    const { selectRun } = useActions(wizardRunDetailsLogic)

    useEffect(() => {
        selectRun(run, source)
        return () => selectRun(null)
    }, [run, selectRun, source])

    return <WizardRunDetailsDialog tasks={tasks} onClose={onClose} />
}
