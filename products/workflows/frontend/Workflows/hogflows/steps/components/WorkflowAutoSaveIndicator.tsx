import { useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { LastSavedIndicator } from 'lib/components/LastSavedIndicator'
import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'

import { workflowLogic } from '../../../workflowLogic'

// Mirrors the status bar's save-state narration inside surfaces that cover it (the fullscreen
// email editor), so a user editing with live propagation can still see whether edits persisted.
export function WorkflowAutoSaveIndicator(): JSX.Element | null {
    const {
        logicProps,
        isAutoSavePending,
        workflowLoading,
        autoSaveEnabled,
        workflowChanged,
        workflowHasErrors,
        lastSavedAt,
    } = useValues(workflowLogic)
    const showSaving = useDebouncedValue(isAutoSavePending || workflowLoading, 1000)

    // New and template-editing workflows only save through the scene header, so a save-state
    // readout here would be misleading.
    if (!logicProps.id || logicProps.id === 'new' || logicProps.editTemplateId) {
        return null
    }

    if (workflowChanged && workflowHasErrors) {
        return <span className="text-xs text-warning">Auto-save paused: fix the errors in this workflow</span>
    }
    if (workflowChanged && !autoSaveEnabled) {
        return <span className="text-xs text-warning">Auto-save is off. You have unsaved changes</span>
    }
    if (autoSaveEnabled && showSaving) {
        return (
            <span className="text-xs text-tertiary flex items-center gap-1">
                <Spinner textColored /> Saving…
            </span>
        )
    }
    return lastSavedAt ? <LastSavedIndicator timestamp={lastSavedAt} /> : null
}
