import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { Resizer } from 'lib/components/Resizer/Resizer'
import { ResizerLogicProps, resizerLogic } from 'lib/components/Resizer/resizerLogic'
import { capitalizeFirstLetter } from 'lib/utils/strings'

import {
    HOG_FLOW_EDITOR_DEFAULT_PANEL_WIDTH,
    HOG_FLOW_EDITOR_MODES,
    HogFlowEditorMode,
    hogFlowEditorLogic,
} from '../hogFlowEditorLogic'
import { HogFlowEditorPanelBuild } from './HogFlowEditorPanelBuild'
import { HogFlowEditorPanelBuildDetail } from './HogFlowEditorPanelBuildDetail'
import { HogFlowEditorPanelLogs } from './HogFlowEditorPanelLogs'
import { HogFlowEditorPanelMetrics } from './HogFlowEditorPanelMetrics'
import { HogFlowEditorPanelResizeHandle } from './HogFlowEditorPanelResizeHandle'
import { HogFlowEditorPanelSelectedStep } from './HogFlowEditorPanelSelectedStep'
import { HogFlowEditorPanelVariables } from './HogFlowEditorPanelVariables'
import { EmailActionTestContent } from './testing/HogFlowEditorNotificationPanelTest'
import { HogFlowEditorPanelTest } from './testing/HogFlowEditorPanelTest'

export function HogFlowEditorPanel({
    layout = 'floating',
}: { layout?: 'floating' | 'panel' } = {}): JSX.Element | null {
    const { panelWidth, selectedNode, mode, workflow } = useValues(hogFlowEditorLogic)
    const { clearPanelWidth, setMode, setPanelWidth, setSelectedNodeId } = useActions(hogFlowEditorLogic)
    const panelRef = useRef<HTMLDivElement>(null)
    const resizerProps: ResizerLogicProps = {
        logicKey: 'hog-flow-simple-panel',
        containerRef: panelRef,
        placement: 'left',
        persistent: true,
    }
    const { desiredSize: panelLayoutWidth } = useValues(resizerLogic(resizerProps))

    const variablesCount = workflow?.variables?.length || 0

    const tabs: LemonTab<HogFlowEditorMode>[] = HOG_FLOW_EDITOR_MODES.map((mode) => ({
        label: (
            <>
                {capitalizeFirstLetter(mode)}
                {mode === 'variables' && variablesCount > 0 && (
                    <LemonBadge.Number
                        count={variablesCount}
                        maxDigits={2}
                        size="small"
                        status="muted"
                        className="ml-1"
                    />
                )}
            </>
        ),
        key: mode,
    }))

    return (
        <div
            ref={panelRef}
            className={clsx(
                'flex min-h-0 max-h-full flex-col justify-end overflow-hidden',
                layout === 'floating'
                    ? 'absolute right-0 max-w-full p-2'
                    : 'relative h-full shrink-0 bg-surface-primary @max-[48rem]/workflow-editor:!h-96 @max-[48rem]/workflow-editor:!min-w-0 @max-[48rem]/workflow-editor:!w-full @max-[48rem]/workflow-editor:!max-w-full @max-[48rem]/workflow-editor:border-t'
            )}
            style={
                layout === 'floating'
                    ? { width: panelWidth ?? HOG_FLOW_EDITOR_DEFAULT_PANEL_WIDTH }
                    : { width: panelLayoutWidth ?? '50%', minWidth: '20rem', maxWidth: '70%' }
            }
        >
            {layout === 'floating' ? (
                <HogFlowEditorPanelResizeHandle
                    width={panelWidth ?? HOG_FLOW_EDITOR_DEFAULT_PANEL_WIDTH}
                    onResize={setPanelWidth}
                    onReset={clearPanelWidth}
                />
            ) : (
                <div className="@max-[48rem]/workflow-editor:hidden">
                    <Resizer {...resizerProps} />
                </div>
            )}
            <div
                className={clsx(
                    'relative z-10 flex min-h-0 flex-col overflow-hidden bg-surface-primary',
                    layout === 'floating'
                        ? 'max-h-full rounded-md border shadow-[0_3px_0_var(--border)]'
                        : 'h-full !rounded-none'
                )}
            >
                <div className="flex shrink-0 items-center gap-2 border-b">
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

                    <div className="min-w-0 flex-1">
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
