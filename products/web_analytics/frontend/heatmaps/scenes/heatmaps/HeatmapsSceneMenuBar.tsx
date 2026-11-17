import { router } from 'kea-router'

import { IconMessage, IconPlus, IconPlusSmall } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { AccessControlAction } from 'lib/components/AccessControlAction'
import { RenderKeybind } from 'lib/components/Shortcuts/RenderKeybind'
import { Shortcut } from 'lib/components/Shortcuts/Shortcut'
import { keyBinds } from 'lib/components/Shortcuts/shortcuts'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { Scene } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

const RESOURCE_TYPE = 'heatmaps'
// pinned: the feedback survey's selector targets this element id
const FEEDBACK_BUTTON_ID = 'heatmaps-feedback-button'

export function HeatmapsSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <HeatmapsSceneMenuBarInner /> : null
}

function HeatmapsSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-heatmap`,
            label: 'New heatmap',
            icon: <IconPlusSmall />,
            disabledReason:
                getAccessControlDisabledReason(AccessControlResourceType.Heatmap, AccessControlLevel.Editor) ??
                undefined,
            shortcut: <RenderKeybind keybind={[keyBinds.new]} minimal />,
            onSelect: () => router.actions.push(urls.heatmap('new')),
            pinned: {
                order: 1,
                variant: 'primary',
                render: () => (
                    <Shortcut
                        name="NewHeatmap"
                        keybind={[keyBinds.new]}
                        intent="New heatmap"
                        interaction="click"
                        scope={Scene.Heatmaps}
                    >
                        <AccessControlAction
                            resourceType={AccessControlResourceType.Heatmap}
                            minAccessLevel={AccessControlLevel.Editor}
                        >
                            <Button
                                variant="primary"
                                render={<LinkPrimitive to={urls.heatmap('new')} />}
                                data-attr="heatmaps-new-heatmap-button"
                                tooltip="New heatmap"
                            >
                                <IconPlus />
                                New heatmap
                            </Button>
                        </AccessControlAction>
                    </Shortcut>
                ),
            },
        },
        {
            group: 'view',
            id: `${RESOURCE_TYPE}-menubar-send-feedback`,
            label: 'Send feedback',
            icon: <IconMessage />,
            opensFloatingUi: true,
            // The feedback survey opens on a click of the title button, so the row forwards its click there.
            onSelect: () => document.getElementById(FEEDBACK_BUTTON_ID)?.click(),
            pinned: {
                order: 1,
                variant: 'secondary',
                render: () => (
                    <Button variant="outline" id={FEEDBACK_BUTTON_ID} data-attr="heatmaps-feedback-button">
                        Send feedback
                    </Button>
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
