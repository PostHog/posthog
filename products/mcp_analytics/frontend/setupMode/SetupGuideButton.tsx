import { useActions } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { mcpSetupModeLogic } from './mcpSetupModeLogic'

export const SETUP_GUIDE_LABEL = 'Setup guide'

function SetupGuideButtonContent({ quill }: { quill: boolean }): JSX.Element {
    const { openSetupMode } = useActions(mcpSetupModeLogic)
    return quill ? (
        <Button variant="outline" onClick={() => openSetupMode('scene_button')} data-attr="mcp-analytics-reopen-setup">
            {SETUP_GUIDE_LABEL}
        </Button>
    ) : (
        <LemonButton
            type="secondary"
            size="small"
            onClick={() => openSetupMode('scene_button')}
            data-attr="mcp-analytics-reopen-setup"
        >
            {SETUP_GUIDE_LABEL}
        </LemonButton>
    )
}

/** Reopens setup mode from the scene, for a project that already has calls. Mounts nothing with the flag off. */
export function SetupGuideButton({ quill }: { quill: boolean }): JSX.Element | null {
    const enabled = useFeatureFlag('MCP_ANALYTICS_SETUP_MODE')
    return enabled ? <SetupGuideButtonContent quill={quill} /> : null
}
