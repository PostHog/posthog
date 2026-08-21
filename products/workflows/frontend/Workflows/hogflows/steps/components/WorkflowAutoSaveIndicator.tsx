import { useActions, useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

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
        autoSaveBlockedByValidation,
        externallyEdited,
        lastSavedAt,
    } = useValues(workflowLogic)
    const { loadWorkflow, keepMyWorkflowVersion } = useActions(workflowLogic)
    const showSaving = useDebouncedValue(isAutoSavePending || workflowLoading, 1000)

    // New and template-editing workflows only save through the scene header, so a save-state
    // readout here would be misleading.
    if (!logicProps.id || logicProps.id === 'new' || logicProps.editTemplateId) {
        return null
    }

    // The scene-level conflict banner is covered by the surface hosting this indicator, so the
    // choice it carries has to be reachable here too.
    if (externallyEdited) {
        return (
            <span className="text-xs text-warning flex items-center gap-2 whitespace-nowrap">
                Updated elsewhere
                <LemonButton size="xsmall" type="secondary" onClick={() => keepMyWorkflowVersion()}>
                    Keep mine
                </LemonButton>
                <LemonButton size="xsmall" type="primary" onClick={() => loadWorkflow()}>
                    Reload
                </LemonButton>
            </span>
        )
    }
    if (workflowChanged && autoSaveBlockedByValidation) {
        return <span className="text-xs text-warning whitespace-nowrap">Auto-save paused: name your workflow</span>
    }
    if (workflowChanged && !autoSaveEnabled) {
        return (
            <span className="text-xs text-warning whitespace-nowrap">Auto-save is off. You have unsaved changes</span>
        )
    }
    if (autoSaveEnabled && showSaving) {
        return (
            <span className="text-xs text-tertiary flex items-center gap-1 whitespace-nowrap">
                <Spinner textColored /> Saving…
            </span>
        )
    }
    return lastSavedAt ? <LastSavedIndicator timestamp={lastSavedAt} /> : null
}
