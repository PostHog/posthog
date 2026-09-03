import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import { HOG_FLOW_EDITOR_MODES, HogFlowEditorMode, hogFlowEditorLogic } from '../hogFlowEditorLogic'
import { HogFlowEditorPanelBuild } from './HogFlowEditorPanelBuild'
import { HogFlowEditorPanelBuildDetail } from './HogFlowEditorPanelBuildDetail'
import { HogFlowEditorPanelLogs } from './HogFlowEditorPanelLogs'
import { HogFlowEditorPanelMetrics } from './HogFlowEditorPanelMetrics'
import { HogFlowEditorPanelSelectedStep } from './HogFlowEditorPanelSelectedStep'
import { HogFlowEditorPanelVariables } from './HogFlowEditorPanelVariables'
import { EmailActionTestContent } from './testing/HogFlowEditorNotificationPanelTest'
import { HogFlowEditorPanelTest } from './testing/HogFlowEditorPanelTest'

export function HogFlowEditorPanel({
    layout = 'floating',
}: {
    layout?: 'floating' | 'panel'
} = {}): JSX.Element | null {
    const { selectedNode, mode, workflow } = useValues(hogFlowEditorLogic)
    const { setMode, setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const panelRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        logicKey: 'hog-flow-simple-panel',
        containerRef: panelRef,
        placement: 'left',
        persistent: true,
    }
    const { desiredSize: panelWidth } = useValues(resizerLogic(resizerProps))

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

    const width = mode !== 'build' ? '37rem' : selectedNode ? '37rem' : '25rem'

    return (
        <div
            ref={panelRef}
            className={clsx(
                'flex min-h-0 flex-col m-0 overflow-hidden max-h-full justify-end',
                layout === 'floating'
                    ? 'absolute right-0 p-2 transition-[width]'
                    : 'relative h-full shrink-0 bg-surface-primary'
            )}
            style={
                layout === 'floating'
                    ? { width }
                    : { width: panelWidth ?? '50%', minWidth: `min(${width}, 70%)`, maxWidth: '70%' }
            }
        >
            {layout === 'panel' && <Resizer {...resizerProps} />}
            <div
                className={clsx(
                    'relative flex min-h-0 flex-col rounded-md overflow-hidden bg-surface-primary z-10',
                    layout === 'floating' ? 'max-h-full' : 'h-full !rounded-none'
                )}
                style={
                    layout === 'floating'
                        ? {
                              border: '1px solid var(--border)',
                              boxShadow: '0 3px 0 var(--border)',
                          }
                        : undefined
                }
            >
                <div className="flex shrink-0 gap-2 border-b items-center">
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
                            aria-label="Back to steps"
                            data-attr="workflow-panel-back"
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
                </div>

                {selectedNode && ['build', 'metrics', 'test', 'logs'].includes(mode) && (
                    <HogFlowEditorPanelSelectedStep />
                )}
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
    )
}
