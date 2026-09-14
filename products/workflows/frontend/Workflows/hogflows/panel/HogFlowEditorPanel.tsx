import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
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

export function HogFlowEditorPanel(): JSX.Element | null {
    const { panelWidth, selectedNode, mode, workflow } = useValues(hogFlowEditorLogic)
    const { clearPanelWidth, setMode, setPanelWidth, setSelectedNodeId } = useActions(hogFlowEditorLogic)

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
            className="absolute right-0 flex max-h-full max-w-full flex-col justify-end overflow-hidden p-2"
            style={{ width: panelWidth ?? HOG_FLOW_EDITOR_DEFAULT_PANEL_WIDTH }}
        >
            <HogFlowEditorPanelResizeHandle
                width={panelWidth ?? HOG_FLOW_EDITOR_DEFAULT_PANEL_WIDTH}
                onResize={setPanelWidth}
                onReset={clearPanelWidth}
            />
            <div className="relative z-10 flex max-h-full flex-col overflow-hidden rounded-md border bg-surface-primary shadow-[0_3px_0_var(--border)]">
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
