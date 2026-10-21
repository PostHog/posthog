import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useRef } from 'react'

import { IconArrowLeft, IconX } from '@posthog/icons'
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

export interface HogFlowEditorPanelProps {
    layout?: 'floating' | 'panel' | 'docked'
    onClose?: () => void
    view?: { title: string; content: JSX.Element }
}

export function HogFlowEditorPanel({
    layout = 'floating',
    onClose,
    view,
}: HogFlowEditorPanelProps = {}): JSX.Element | null {
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
    const width = panelWidth ?? HOG_FLOW_EDITOR_DEFAULT_PANEL_WIDTH

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
    // A docked panel is too narrow for every tab, and Variables has its own button beside the canvas.
    const shownTabs = layout === 'docked' ? tabs.filter((tab) => tab.key !== 'variables') : tabs
    const title = view?.title ?? (shownTabs.some((tab) => tab.key === mode) ? null : capitalizeFirstLetter(mode))

    return (
        <div
            ref={panelRef}
            data-attr="workflow-editor-panel"
            className={clsx(
                'flex min-h-0 max-h-full flex-col justify-end overflow-hidden @max-[48rem]/workflow-editor:!relative @max-[48rem]/workflow-editor:!min-w-0 @max-[48rem]/workflow-editor:!w-full @max-[48rem]/workflow-editor:!max-w-full @max-[48rem]/workflow-editor:shrink-0',
                layout === 'floating' && 'absolute right-0 max-w-full p-2 @max-[48rem]/workflow-editor:!h-96',
                layout === 'panel' &&
                    'relative h-full shrink-0 bg-surface-primary @max-[48rem]/workflow-editor:!h-96 @max-[48rem]/workflow-editor:border-t',
                layout === 'docked' &&
                    'relative h-full min-w-80 max-w-[calc(100%-30rem)] shrink-0 border-l bg-surface-primary @max-[48rem]/workflow-editor:!h-1/2 @max-[48rem]/workflow-editor:border-t @max-[48rem]/workflow-editor:border-l-0'
            )}
            style={
                layout === 'panel'
                    ? { width: panelLayoutWidth ?? '50%', minWidth: '20rem', maxWidth: '70%' }
                    : { width }
            }
        >
            {layout !== 'panel' ? (
                <HogFlowEditorPanelResizeHandle width={width} onResize={setPanelWidth} onReset={clearPanelWidth} />
            ) : (
                <div className="@max-[48rem]/workflow-editor:hidden">
                    <Resizer {...resizerProps} />
                </div>
            )}
            <div
                className={clsx(
                    'relative z-10 flex min-h-0 flex-col overflow-hidden bg-surface-primary',
                    layout === 'floating'
                        ? 'max-h-full rounded-md border shadow-[0_3px_0_var(--border)] @max-[48rem]/workflow-editor:h-full'
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
                            aria-label="Back to steps"
                            size="small"
                            icon={<IconArrowLeft />}
                            onClick={() => setSelectedNodeId(null)}
                            disabled={!selectedNode}
                        />
                    </div>

                    <div className="min-w-0 flex-1">
                        {title ? (
                            <h3 className="m-0 truncate py-2 text-sm font-semibold">{title}</h3>
                        ) : (
                            <LemonTabs
                                activeKey={mode}
                                onChange={(key) => setMode(key)}
                                tabs={shownTabs}
                                size={layout === 'docked' ? 'small' : undefined}
                                barClassName="-mb-px "
                            />
                        )}
                    </div>
                    {onClose && (
                        <div className="shrink-0 p-1">
                            <LemonButton
                                size="small"
                                icon={<IconX />}
                                tooltip="Close the panel (Esc)"
                                data-attr="workflow-tile-close-panel"
                                onClick={onClose}
                            />
                        </div>
                    )}
                </div>

                {view ? (
                    view.content
                ) : (
                    <>
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
                    </>
                )}
            </div>
        </div>
    )
}
