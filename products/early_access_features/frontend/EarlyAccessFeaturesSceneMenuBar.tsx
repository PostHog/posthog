import { router } from 'kea-router'

import { IconPlusSmall } from '@posthog/icons'
import { Button } from '@posthog/quill'

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

const RESOURCE_TYPE = 'early-access-features'

export function EarlyAccessFeaturesSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <EarlyAccessFeaturesSceneMenuBarInner /> : null
}

function EarlyAccessFeaturesSceneMenuBarInner(): JSX.Element {
    const disabledReason =
        getAccessControlDisabledReason(AccessControlResourceType.EarlyAccessFeature, AccessControlLevel.Editor) ??
        undefined

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-feature`,
            label: 'New feature',
            icon: <IconPlusSmall />,
            disabledReason,
            shortcut: <RenderKeybind keybind={[keyBinds.new]} minimal />,
            onSelect: () => router.actions.push(urls.earlyAccessFeature('new')),
            pinned: {
                order: 1,
                variant: 'primary',
                // The title button also registers the "new" keyboard shortcut.
                render: () => (
                    <Shortcut
                        name="NewEarlyAccessFeature"
                        keybind={[keyBinds.new]}
                        intent="New early access feature"
                        interaction="click"
                        scope={Scene.EarlyAccessFeatures}
                    >
                        <Button
                            variant="primary"
                            render={<LinkPrimitive to={disabledReason ? undefined : urls.earlyAccessFeature('new')} />}
                            tooltip="New feature"
                            data-attr="create-feature"
                            disabledReason={disabledReason}
                        >
                            New feature
                        </Button>
                    </Shortcut>
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
