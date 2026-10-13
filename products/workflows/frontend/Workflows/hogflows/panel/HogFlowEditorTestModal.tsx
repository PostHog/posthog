import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { EmailActionTestContent } from './testing/HogFlowEditorNotificationPanelTest'
import { HogFlowEditorPanelTest } from './testing/HogFlowEditorPanelTest'

export function HogFlowEditorTestModal(): JSX.Element {
    const { mode, selectedNode } = useValues(hogFlowEditorLogic)
    const { setMode } = useActions(hogFlowEditorLogic)
    const Step = useHogFlowStep(selectedNode?.data)

    return (
        <LemonModal
            isOpen={mode === 'test'}
            onClose={() => setMode('build')}
            title={
                selectedNode ? (
                    <span className="flex items-center gap-2">
                        <span className="flex text-lg" style={{ color: Step?.color }}>
                            {Step?.icon}
                        </span>
                        Test {selectedNode.data.name}
                    </span>
                ) : (
                    'Test workflow'
                )
            }
            width={720}
        >
            {/* The test panes scroll inside flex areas, so they need a fixed height to scroll within. */}
            <div className="-mx-4 flex h-[60vh] flex-col overflow-hidden" data-attr="workflow-editor-test">
                {selectedNode?.data.type === 'function_email' ? <EmailActionTestContent /> : <HogFlowEditorPanelTest />}
            </div>
        </LemonModal>
    )
}
