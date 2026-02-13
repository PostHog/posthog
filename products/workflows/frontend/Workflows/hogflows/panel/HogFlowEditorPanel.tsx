import { useReactFlow } from '@xyflow/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { IconArrowLeft, IconCollapse45, IconExpand45, IconTrash } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonTab, LemonTabs, Tooltip } from '@posthog/lemon-ui'

import { capitalizeFirstLetter } from 'lib/utils'

import { workflowLogic } from '../../workflowLogic'
import { HOG_FLOW_EDITOR_MODES, HogFlowEditorMode, hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { useHogFlowStep } from '../steps/HogFlowSteps'
import { HogFlowEditorPanelBuild } from './HogFlowEditorPanelBuild'
import { HogFlowEditorPanelBuildDetail } from './HogFlowEditorPanelBuildDetail'
import { HogFlowEditorPanelLogs } from './HogFlowEditorPanelLogs'
import { HogFlowEditorPanelMetrics } from './HogFlowEditorPanelMetrics'
import { HogFlowEditorPanelVariables } from './HogFlowEditorPanelVariables'
import { EmailActionTestContent } from './testing/HogFlowEditorNotificationPanelTest'
import { HogFlowEditorPanelTest } from './testing/HogFlowEditorPanelTest'

export function HogFlowEditorPanel(): JSX.Element | null {
    const { selectedNode, mode, selectedNodeCanBeDeleted, workflow, isPanelFullscreen } = useValues(hogFlowEditorLogic)
    const { setMode, setSelectedNodeId, setPanelFullscreen } = useActions(hogFlowEditorLogic)
    const { deleteElements } = useReactFlow()

    const variablesCount = workflow?.variables?.length || 0

    const tabs: LemonTab<HogFlowEditorMode>[] = HOG_FLOW_EDITOR_MODES.map((mode) => ({
        label: (
            <>
                {capitalizeFirstLetter(mode)}
                {mode === 'variables' && variablesCount > 0 && (
                    <span className="ml-1 text-muted">({variablesCount})</span>
                )}
            </>
        ),
        key: mode,
    }))

    const width = isPanelFullscreen ? '100%' : mode !== 'build' ? '42rem' : selectedNode ? '42rem' : '30rem'

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'Escape' && isPanelFullscreen) {
                e.stopPropagation()
                setPanelFullscreen(false)
            }
            if (e.key === 'f' && (e.metaKey || e.ctrlKey) && e.shiftKey) {
                e.preventDefault()
                setPanelFullscreen(!isPanelFullscreen)
            }
        }
        document.addEventListener('keydown', handleKeyDown, true)
        return () => document.removeEventListener('keydown', handleKeyDown, true)
    }, [isPanelFullscreen, setPanelFullscreen])

    const Step = useHogFlowStep(selectedNode?.data)
    const { actionValidationErrorsById } = useValues(workflowLogic)
    const validationResult = actionValidationErrorsById[selectedNode?.id ?? '']

    return (
        <div
            className={clsx(
                'absolute flex flex-col m-0 p-2 overflow-hidden max-h-full right-0',
                isPanelFullscreen ? 'inset-0 z-20 justify-stretch' : 'justify-end transition-[width]'
            )}
            style={isPanelFullscreen ? undefined : { width }}
        >
            <div
                className={clsx(
                    'relative flex flex-col rounded-md overflow-hidden bg-surface-primary max-h-full z-10',
                    isPanelFullscreen && 'h-full'
                )}
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
                        <span className="flex gap-1 items-center font-medium rounded-md min-w-0">
                            <span className="text-lg">{Step?.icon}</span>
                            <Tooltip title={selectedNode.data.name}>
                                <span className="font-semibold truncate">{selectedNode.data.name}</span>
                            </Tooltip>
                            {validationResult?.valid === false && (
                                <Tooltip title="Some fields need attention">
                                    <div>
                                        <LemonBadge status="warning" size="small" content="!" />
                                    </div>
                                </Tooltip>
                            )}
                            {selectedNode.deletable && (
                                <LemonButton
                                    size="small"
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

                    <Tooltip
                        title={
                            isPanelFullscreen
                                ? 'Exit full screen (Esc)'
                                : `Full screen (${navigator.platform.includes('Mac') ? '⌘' : 'Ctrl'}+⇧+F)`
                        }
                    >
                        <LemonButton
                            size="small"
                            className="mr-1"
                            icon={isPanelFullscreen ? <IconCollapse45 /> : <IconExpand45 />}
                            onClick={() => setPanelFullscreen(!isPanelFullscreen)}
                        />
                    </Tooltip>
                </div>

                <div className="flex flex-col flex-1 min-h-0 overflow-hidden">
                    {mode === 'build' && (
                        <>{!selectedNode ? <HogFlowEditorPanelBuild /> : <HogFlowEditorPanelBuildDetail />}</>
                    )}
                    {mode === 'variables' && <HogFlowEditorPanelVariables />}
                    {mode === 'test' &&
                        (selectedNode?.data?.type === 'function_email' ? (
                            <EmailActionTestContent />
                        ) : (
                            <HogFlowEditorPanelTest />
                        ))}
                    {mode === 'metrics' && <HogFlowEditorPanelMetrics />}
                    {mode === 'logs' && <HogFlowEditorPanelLogs />}
                </div>
            </div>
        </div>
    )
}
