import { useActions, useValues } from 'kea'

import { LemonModal } from '@posthog/lemon-ui'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMCPAnalyticsWizardCommand } from '../onboarding/MCPAnalyticsInstall'
import { mcpSetupModeLogic } from './mcpSetupModeLogic'
import { MCPSetupModeView } from './MCPSetupModeView'

function MCPSetupModeOverlay(): JSX.Element | null {
    const { isOpen, setupPath, step, connectState, recentCalls, recentCallsFailed, agentPrompt } =
        useValues(mcpSetupModeLogic)
    const { exitSetupMode, goToUsefulStep, askPostHogAI } = useActions(mcpSetupModeLogic)
    // Self-hosted can't run the Wizard against cloud, so it gets no command to copy.
    const { command, isCloudOrDev } = useMCPAnalyticsWizardCommand()

    if (!isOpen || !setupPath) {
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
                setupPath={setupPath}
                agentPrompt={agentPrompt}
                wizardCommand={isCloudOrDev ? command : null}
                onExit={exitSetupMode}
                onAskPostHogAI={askPostHogAI}
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
