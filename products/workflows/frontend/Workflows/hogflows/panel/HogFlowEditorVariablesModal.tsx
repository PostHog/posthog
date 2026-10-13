import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowEditorPanelVariables } from './HogFlowEditorPanelVariables'

export function HogFlowEditorVariablesModal(): JSX.Element {
    const { mode } = useValues(hogFlowEditorLogic)
    const { setMode } = useActions(hogFlowEditorLogic)

    return (
        <LemonModal
            isOpen={mode === 'variables'}
            onClose={() => setMode('build')}
            title="Variables"
            description="Values your steps can read and write while the workflow runs."
            width={640}
        >
            <div className="-mx-4" data-attr="workflow-editor-variables">
                <HogFlowEditorPanelVariables />
            </div>
        </LemonModal>
    )
}
