import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { mcpSetupModeLogic } from './mcpSetupModeLogic'
import { MCPSetupModeView } from './MCPSetupModeView'

function MCPSetupModeOverlay(): JSX.Element | null {
    const { isOpen, step, connectState, recentCalls, recentCallsFailed, agentPrompt } = useValues(mcpSetupModeLogic)
    const { exitSetupMode, goToUsefulStep } = useActions(mcpSetupModeLogic)

    if (!isOpen) {
        return null
    }
    return (
        <LemonModal
            // The logic handles Escape, so the modal itself never closes.
            closable={false}
            fullScreen
            simple
            // The gate remounts this host when the first call lands. Showing the modal at full opacity from
            // its first frame, and unmounting it on exit, keeps the swap and the exit free of a fade over the scene.
            className="!opacity-100 !transform-none"
            data-attr="mcp-analytics-setup-mode"
        >
            <MCPSetupModeView
                step={step}
                connectState={connectState}
                recentCalls={recentCalls}
                recentCallsFailed={recentCallsFailed}
                agentPrompt={agentPrompt}
                onExit={exitSetupMode}
                onGoToUseful={goToUsefulStep}
            />
        </LemonModal>
    )
}

/**
 * Mounted by both the empty state and the scene, because the gate swaps one for the other when the
 * first call lands. The state lives in the URL, so the takeover carries across the swap.
 */
export function MCPSetupMode(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    // Checked here rather than in the logic so that, with the flag off, nothing extra mounts.
    if (!featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_SETUP_MODE]) {
        return null
    }
    return <MCPSetupModeOverlay />
}
