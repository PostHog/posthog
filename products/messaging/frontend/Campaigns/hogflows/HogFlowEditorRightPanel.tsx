import { useReactFlow } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { HogFlowEditorDetailsPanel } from './HogFlowEditorDetailsPanel'
import { HogFlowEditorToolbar } from './HogFlowEditorToolbar'
import { HogFlowEditorPanel } from './components/HogFlowEditorPanel'
import { HogFlowEditorMode, hogFlowEditorLogic } from './hogFlowEditorLogic'
import { getHogFlowStep } from './steps/HogFlowSteps'
import { HogFlowEditorTestPanel, HogFlowTestPanelNonSelected } from './testing/HogFlowEditorTestPanel'

export function HogFlowEditorRightPanel(): JSX.Element | null {
    const { selectedNode, mode, selectedNodeCanBeDeleted } = useValues(hogFlowEditorLogic)
    const { setMode, setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { deleteElements } = useReactFlow()

    const tabs: LemonTab<HogFlowEditorMode>[] = [
        { label: 'Build', key: 'build' },
        { label: 'Test', key: 'test' },
    ]

    let width = selectedNode ? '36rem' : '22rem'
    if (mode === 'test') {
        width = '36rem'
    }

    const Step = selectedNode ? getHogFlowStep(selectedNode.data.type) : null

    return (
        <HogFlowEditorPanel position="right-top" width={width}>
            <div className="flex gap-2 border-b items-center">
                <div
                    className={clsx(
                        'transition-all overflow-hidden flex p-1',
                        !selectedNode ? 'w-2 opacity-0' : 'w-10 opacity-100'
                    )}
                >
                    <LemonButton
                        size="small"
                        icon={<IconArrowLeft />}
                        onClick={() => setSelectedNodeId(null)}
                        disabled={!selectedNode}
                    />
                </div>

                <div className="flex-1">
                    <LemonTabs activeKey={mode} onChange={(key) => setMode(key)} tabs={tabs} barClassName="-mb-px " />
                </div>

                {selectedNode && (
                    <span className="flex gap-1 items-center font-medium rounded-md mr-3">
                        <span className="text-lg">{Step?.icon}</span>
                        <span className="font-semibold">{selectedNode.data.name}</span> step
                        {selectedNode.deletable && (
                            <LemonButton
                                size="xsmall"
                                status="danger"
                                icon={<IconTrash />}
                                onClick={() => {
                                    void deleteElements({ nodes: [selectedNode] })
                                    setSelectedNodeId(null)
                                }}
                                disabledReason={selectedNodeCanBeDeleted ? undefined : 'Clean up branching steps first'}
                            />
                        )}
                    </span>
                )}
            </div>

            {mode === 'build' && <>{!selectedNode ? <HogFlowEditorToolbar /> : <HogFlowEditorDetailsPanel />}</>}
            {mode === 'test' && <>{!selectedNode ? <HogFlowTestPanelNonSelected /> : <HogFlowEditorTestPanel />}</>}
        </HogFlowEditorPanel>
    )
}
