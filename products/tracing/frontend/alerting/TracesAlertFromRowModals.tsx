import { useActions, useValues } from 'kea'
import { useCallback, useEffect, useState } from 'react'

import { TracesAlertCreateModal } from './TracesAlertCreateModal'
import { TracesAlertEditModal } from './TracesAlertEditModal'
import { tracesAlertFormLogic } from './tracesAlertFormLogic'
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
    const closeCreate = useCallback((): void => setCreating(false), [])
    const { editingAlert } = useValues(tracesAlertsLogic)
    const { closeEditAlertModal } = useActions(tracesAlertsLogic)
    // The same props the create modal passes, so this mount keeps a save going after Escape closes it.
    const { isAlertFormSubmitting } = useValues(
        tracesAlertFormLogic({ alert: null, initialForm, onSubmitSuccess: closeCreate })
    )

    useEffect(() => {
        if (!creating && !isAlertFormSubmitting && editingAlert === null) {
            onDone()
        }
    }, [creating, isAlertFormSubmitting, editingAlert, onDone])

    return (
        <>
            <TracesAlertCreateModal isOpen={creating} onClose={closeCreate} initialForm={initialForm} />
            <TracesAlertEditModal alert={editingAlert} onClose={closeEditAlertModal} />
        </>
    )
}
