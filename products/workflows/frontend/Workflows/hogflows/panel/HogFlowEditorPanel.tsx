import clsx from 'clsx'
import { useActions, useValues } from 'kea'

import { IconArrowLeft } from '@posthog/icons'
import { LemonBadge, LemonButton, LemonTab, LemonTabs } from '@posthog/lemon-ui'

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

export function HogFlowEditorPanel(): JSX.Element | null {
    const { selectedNode, mode, workflow } = useValues(hogFlowEditorLogic)
    const { setMode, setSelectedNodeId } = useActions(hogFlowEditorLogic)

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

    const width = mode !== 'build' ? '37rem' : selectedNode ? '37rem' : '25rem'

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
