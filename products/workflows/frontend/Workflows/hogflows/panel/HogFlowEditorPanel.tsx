import { useActions, useValues } from 'kea'

import { IconArrowLeft, IconX } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

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
    onClose?: () => void
    view?: { title: string; content: JSX.Element }
}

export function HogFlowEditorPanel({ onClose, view }: HogFlowEditorPanelProps = {}): JSX.Element | null {
    const { panelWidth, selectedNode, mode, workflow } = useValues(hogFlowEditorLogic)
    const { clearPanelWidth, setMode, setPanelWidth, setSelectedNodeId } = useActions(hogFlowEditorLogic)

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
    // The panel is too narrow for every tab, and Variables has its own button beside the canvas.
    const shownTabs = tabs.filter((tab) => tab.key !== 'variables')
    const title = view?.title ?? (shownTabs.some((tab) => tab.key === mode) ? null : capitalizeFirstLetter(mode))

    return (
        <div
            data-attr="workflow-editor-panel"
            className="relative flex h-full min-h-0 max-h-full min-w-80 max-w-[calc(100%-30rem)] shrink-0 flex-col justify-end overflow-hidden border-l bg-surface-primary @max-[48rem]/workflow-editor:!relative @max-[48rem]/workflow-editor:!h-1/2 @max-[48rem]/workflow-editor:!min-w-0 @max-[48rem]/workflow-editor:!w-full @max-[48rem]/workflow-editor:!max-w-full @max-[48rem]/workflow-editor:shrink-0 @max-[48rem]/workflow-editor:border-t @max-[48rem]/workflow-editor:border-l-0"
            style={{ width }}
        >
            <HogFlowEditorPanelResizeHandle width={width} onResize={setPanelWidth} onReset={clearPanelWidth} />
            <div className="relative z-10 flex h-full min-h-0 flex-col overflow-hidden !rounded-none bg-surface-primary">
                <div className="flex shrink-0 items-center gap-2 border-b">
                    <div
                        className={`transition-all overflow-hidden flex p-1 ${
                            !selectedNode ? 'w-2 opacity-0' : 'w-10 opacity-100'
                        }`}
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
                                size="small"
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
