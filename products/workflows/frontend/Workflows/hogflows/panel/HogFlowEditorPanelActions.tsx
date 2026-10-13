import { useActions, useValues } from 'kea'

import { IconBrackets, IconFlask } from '@posthog/icons'
import { LemonBadge, LemonButton } from '@posthog/lemon-ui'

import { TRIGGER_NODE_ID } from '../../workflowLogic'
import { hogFlowEditorLogic } from '../hogFlowEditorLogic'

export function HogFlowEditorPanelActions(): JSX.Element {
    const { mode, selectedNodeId, workflow } = useValues(hogFlowEditorLogic)
    const { setMode, setSelectedNodeId } = useActions(hogFlowEditorLogic)

    const variablesCount = workflow?.variables?.length || 0

    return (
        <div className="flex shrink-0 items-center gap-1 rounded-md border bg-surface-primary p-0.5 shadow-sm">
            <LemonButton
                size="small"
                icon={<IconBrackets />}
                active={mode === 'variables'}
                onClick={() => setMode(mode === 'variables' ? 'build' : 'variables')}
                tooltip="Values your steps can read and write"
                data-attr="workflow-editor-variables-button"
            >
                Variables
                {variablesCount > 0 && (
                    <LemonBadge.Number
                        count={variablesCount}
                        maxDigits={2}
                        size="small"
                        status="muted"
                        className="ml-1"
                    />
                )}
            </LemonButton>
            <LemonButton
                size="small"
                icon={<IconFlask />}
                active={mode === 'test'}
                onClick={() => {
                    if (mode === 'test') {
                        setMode('build')
                        return
                    }
                    setMode('test')
                    if (!selectedNodeId) {
                        setSelectedNodeId(TRIGGER_NODE_ID)
                    }
                }}
                tooltip={selectedNodeId ? 'Test this step' : 'Test the workflow, starting from the trigger'}
                data-attr="workflow-editor-test-button"
            >
                Test
            </LemonButton>
        </div>
    )
}
