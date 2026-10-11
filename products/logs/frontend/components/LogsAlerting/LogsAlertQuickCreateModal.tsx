import { useActions, useValues } from 'kea'

import { LogsAlertCreateModal } from './LogsAlertCreateModal'
import { logsAlertQuickCreateLogic } from './logsAlertQuickCreateLogic'

/** The create-only alert modal launched from a log row in the viewer, prefilled from that log. */
export function LogsAlertQuickCreateModal(): JSX.Element | null {
    const { seed } = useValues(logsAlertQuickCreateLogic)
    const { closeQuickCreateModal } = useActions(logsAlertQuickCreateLogic)

    if (!seed) {
        return null
    }
    return <LogsAlertCreateModal isOpen onClose={closeQuickCreateModal} seed={seed} />
}
