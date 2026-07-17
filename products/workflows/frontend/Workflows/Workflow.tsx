import { useActions, useValues } from 'kea'

import { LemonBanner, LemonButton, SpinnerOverlay } from '@posthog/lemon-ui'

import { HogFlowEditor } from './hogflows/HogFlowEditor'
import { WorkflowLogicProps, workflowLogic } from './workflowLogic'

export function Workflow(props: WorkflowLogicProps): JSX.Element {
    const { originalWorkflow, workflowLoading, externallyEdited, isSyncingExternalEdit } = useValues(
        workflowLogic(props)
    )
    const { loadWorkflow, keepMyWorkflowVersion } = useActions(workflowLogic(props))

    return (
        <div className="flex flex-col grow relative border rounded-md">
            {/* Brief working/disabled overlay while we reconcile to an edit made elsewhere (clean state). */}
            {isSyncingExternalEdit && <SpinnerOverlay />}
            {externallyEdited && (
                <LemonBanner type="warning" className="m-2">
                    <div className="flex items-center justify-between gap-2">
                        <span>
                            This workflow was updated elsewhere (for example via the API or an AI assistant) while you
                            have unsaved changes. Reload to get the latest version, or keep editing — saving will
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
            {!originalWorkflow && workflowLoading ? <SpinnerOverlay /> : <HogFlowEditor />}
        </div>
    )
}
