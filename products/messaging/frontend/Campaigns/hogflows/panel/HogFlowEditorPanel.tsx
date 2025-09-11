import { useReactFlow } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconTrash } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonDivider, LemonTab, LemonTabs, Tooltip } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'

import { campaignLogic } from '../../campaignLogic'
import { HOG_FLOW_EDITOR_MODES, HogFlowEditorMode, hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { HogFlowEditorPanelBuild } from './HogFlowEditorPanelBuild'
import { HogFlowEditorPanelBuildDetail } from './HogFlowEditorPanelBuildDetail'
import { HogFlowEditorPanelLogs } from './HogFlowEditorPanelLogs'
import { HogFlowEditorPanelMetrics } from './HogFlowEditorPanelMetrics'
import { HogFlowEditorPanelTest } from './testing/HogFlowEditorPanelTest'

export function HogFlowEditorPanel(): JSX.Element | null {
    const { selectedNode, mode, selectedNodeCanBeDeleted } = useValues(hogFlowEditorLogic)
    const { setMode, setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const { deleteElements } = useReactFlow()

    const tabs: LemonTab<HogFlowEditorMode>[] = HOG_FLOW_EDITOR_MODES.map((mode) => ({
        label: capitalizeFirstLetter(mode),
        key: mode,
    }))

    const width = mode !== 'build' ? '36rem' : selectedNode ? '36rem' : '22rem'

    const Step = useHogFlowStep(selectedNode?.data)
    const { actionValidationErrorsById } = useValues(campaignLogic)
    const validationResult = actionValidationErrorsById[selectedNode?.id ?? '']

    return (
        <div
            className="absolute flex flex-col m-0 p-2 overflow-hidden transition-[width] max-h-full right-0 justify-end"
            style={{ width }}
        >
            <div
                className="relative flex flex-col rounded-md overflow-hidden bg-surface-primary max-h-full z-10"
                style={{
                    border: '1px solid var(--border)',
                    boxShadow: '0 3px 0 var(--border)',
                }}
            >
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
                        <LemonTabs
                            activeKey={mode}
                            onChange={(key) => setMode(key)}
                            tabs={tabs}
                            barClassName="-mb-px "
                        />
                    </div>

                    {selectedNode && (
                        <span className="flex gap-1 items-center font-medium rounded-md mr-3">
                            <span className="text-lg">{Step?.icon}</span>
                            <span className="font-semibold">{selectedNode.data.name}</span> step
                            <LemonDivider vertical />
                            {validationResult?.valid === false && (
                                <Tooltip title="Some fields need attention">
                                    <div>
                                        <LemonBadge status="warning" size="small" content="!" />
                                    </div>
                                </Tooltip>
                            )}
                            {selectedNode.deletable && (
                                <LemonButton
                                    size="xsmall"
                                    status="danger"
                                    icon={<IconTrash />}
                                    onClick={() => {
                                        void deleteElements({ nodes: [selectedNode] })
                                        setSelectedNodeId(null)
                                    }}
                                    disabledReason={
                                        selectedNodeCanBeDeleted ? undefined : 'Clean up branching steps first'
                                    }
                                />
                            )}
                        </span>
                    )}
                </div>

                {mode === 'build' && (
                    <>{!selectedNode ? <HogFlowEditorPanelBuild /> : <HogFlowEditorPanelBuildDetail />}</>
                )}
                {mode === 'test' && <HogFlowEditorPanelTest />}
                {mode === 'metrics' && <HogFlowEditorPanelMetrics />}
                {mode === 'logs' && <HogFlowEditorPanelLogs />}
            </div>
        </div>
    )
}
