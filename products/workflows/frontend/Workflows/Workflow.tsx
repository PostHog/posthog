import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { LemonBanner, LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { HogFlowEditor } from './hogflows/HogFlowEditor'
import type { HogFlowEditorLayout } from './hogflows/hogFlowEditorLogic'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'
import { WorkflowStatusBar } from './WorkflowStatusBar'

export function Workflow(props: WorkflowLogicProps): JSX.Element {
    const { originalWorkflow, workflowLoading, externallyEdited, isSyncingExternalEdit } = useValues(
        workflowLogic(props)
    )
    const { loadWorkflow, keepMyWorkflowVersion } = useActions(workflowLogic(props))
    const treeViewEnabled = useFeatureFlag('WORKFLOWS_LINEAR_VIEW')
    const [editorLayout, setEditorLayout] = useState<HogFlowEditorLayout>('simple')

    return (
        <div className="relative flex h-[calc(100vh-13rem)] max-h-full min-h-[25rem] grow flex-col overflow-hidden rounded-md border">
            <WorkflowStatusBar
                {...props}
                editorLayout={editorLayout}
                showEditorLayoutToggle={treeViewEnabled}
                onEditorLayoutChange={setEditorLayout}
            />
            {/* Brief working/disabled overlay while we reconcile to an edit made elsewhere (clean state). */}
            {isSyncingExternalEdit && <SpinnerOverlay />}
            {externallyEdited && (
                <LemonBanner type="warning" className="m-2">
                    <div className="flex items-center justify-between gap-2">
                        <span>
                            This workflow was updated elsewhere (for example via the API or an AI assistant) while you
                            have unsaved changes. Reload to get the latest version, or keep editing and save to
                            overwrite the other changes.
                        </span>
                        <div className="flex items-center gap-2 shrink-0">
                            <LemonButton type="secondary" size="small" onClick={() => keepMyWorkflowVersion()}>
                                Keep mine
                            </LemonButton>
                            <LemonButton type="primary" size="small" onClick={() => loadWorkflow()}>
                                Reload
                            </LemonButton>
                        </div>
                    </div>
                </LemonBanner>
            )}
            {!originalWorkflow && workflowLoading ? (
                <SpinnerOverlay />
            ) : (
                <HogFlowEditor isTreeView={!!treeViewEnabled && editorLayout === 'simple'} />
            )}
        </div>
    )
}
