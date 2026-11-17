import { useActions, useValues } from 'kea'

import { IconDocument } from '@posthog/icons'

import { useSceneFileActions } from 'lib/components/Scenes/useSceneFileActions'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { mcpSetupModeLogic } from './setupMode/mcpSetupModeLogic'
import { SETUP_GUIDE_LABEL } from './setupMode/SetupGuideButton'

const RESOURCE_TYPE = 'mcp-analytics'
const MCP_DOCS_URL = 'https://posthog.com/docs/mcp-analytics/installation'

export function MCPAnalyticsSceneMenuBar(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    if (!featureFlags[FEATURE_FLAGS.SCENE_MENU_BAR]) {
        return null
    }
    // Setup mode's logic mounts only behind its flag, as the title row's Setup guide button does.
    return featureFlags[FEATURE_FLAGS.MCP_ANALYTICS_SETUP_MODE] ? (
        <MCPAnalyticsSceneMenuBarWithSetupGuide />
    ) : (
        <MCPAnalyticsSceneMenuBarInner setupGuideActions={[]} />
    )
}

function MCPAnalyticsSceneMenuBarWithSetupGuide(): JSX.Element {
    const { openSetupMode } = useActions(mcpSetupModeLogic)
    return (
        <MCPAnalyticsSceneMenuBarInner
            setupGuideActions={[
                {
                    group: 'view',
                    id: `${RESOURCE_TYPE}-menubar-setup-guide`,
                    label: SETUP_GUIDE_LABEL,
                    opensFloatingUi: true,
                    onSelect: () => openSetupMode('scene_button'),
                    pinned: { order: 1, variant: 'secondary', dataAttr: 'mcp-analytics-reopen-setup' },
                },
            ]}
        />
    )
}

function MCPAnalyticsSceneMenuBarInner({ setupGuideActions }: { setupGuideActions: SceneAction[] }): JSX.Element {
    const fileActions = useSceneFileActions(RESOURCE_TYPE)

    const actions: SceneAction[] = [
        ...fileActions,
        ...setupGuideActions,
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-documentation`,
            label: 'Documentation',
            icon: <IconDocument />,
            onSelect: () => window.open(MCP_DOCS_URL, '_blank', 'noopener,noreferrer'),
            pinned: { order: 2, variant: 'secondary' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
