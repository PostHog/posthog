import { useActions, useValues } from 'kea'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { HogFlowEditorDetailsPanel } from './HogFlowEditorDetailsPanel'
import { HogFlowEditorToolbar } from './HogFlowEditorToolbar'
import { HogFlowEditorPanel } from './components/HogFlowEditorPanel'
import { HogFlowEditorMode, hogFlowEditorLogic } from './hogFlowEditorLogic'
import { HogFlowEditorTestPanel, HogFlowTestPanelNonSelected } from './testing/HogFlowEditorTestPanel'

export function HogFlowEditorRightPanel(): JSX.Element | null {
    const { selectedNode, mode } = useValues(hogFlowEditorLogic)
    const { setMode } = useActions(hogFlowEditorLogic)

    const tabs: LemonTab<HogFlowEditorMode>[] = [
        { label: 'Build', key: 'build' },
        { label: 'Test', key: 'test' },
    ]

    return (
        <HogFlowEditorPanel position="right-top">
            {!selectedNode ? (
                <>
                    <LemonTabs activeKey={mode} onChange={(key) => setMode(key)} tabs={tabs} barClassName="mb-0 pl-3" />

                    {mode === 'test' ? <HogFlowTestPanelNonSelected /> : <HogFlowEditorToolbar />}
                </>
            ) : mode === 'build' ? (
                <HogFlowEditorDetailsPanel />
            ) : (
                <HogFlowEditorTestPanel />
            )}
        </HogFlowEditorPanel>
    )
}
