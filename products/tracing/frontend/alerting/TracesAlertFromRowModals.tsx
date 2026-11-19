import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { TracesAlertCreateModal } from './TracesAlertCreateModal'
import { TracesAlertEditModal } from './TracesAlertEditModal'
import { tracesAlertsLogic } from './tracesAlertsLogic'
import { TracesAlertFormType } from './tracesAlertUtils'

interface TracesAlertFromRowModalsProps {
    initialForm: TracesAlertFormType
    onDone: () => void
}

/**
 * Creates an alert from an operation row outside the Alerts tab. When a destination fails to save,
 * the create hands the new alert to the edit modal to retry it, so that modal lives here too.
 */
export function TracesAlertFromRowModals({ initialForm, onDone }: TracesAlertFromRowModalsProps): JSX.Element {
    const [creating, setCreating] = useState(true)
    const { editingAlert } = useValues(tracesAlertsLogic)
    const { closeEditAlertModal } = useActions(tracesAlertsLogic)

    useEffect(() => {
        if (!creating && editingAlert === null) {
            onDone()
        }
    }, [creating, editingAlert, onDone])

    return (
        <>
            <TracesAlertCreateModal isOpen={creating} onClose={() => setCreating(false)} initialForm={initialForm} />
            <TracesAlertEditModal alert={editingAlert} onClose={closeEditAlertModal} />
        </>
    )
}
