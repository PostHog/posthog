import { useActions } from 'kea'

import { IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'
import { AccessControlLevel, AccessControlResourceType } from '~/types'

import type { MessagingNavTabKey } from '../messagingTabs'
import { MessagingTabSceneActions } from '../MessagingTabSceneActions'
import { newBroadcastAgentLogic } from './newBroadcastAgentLogic'

const RESOURCE_TYPE = 'broadcasts'

interface BroadcastsSceneMenuBarProps {
    currentTab: MessagingNavTabKey | 'broadcasts' | 'calendar'
}

export function BroadcastsSceneMenuBar(props: BroadcastsSceneMenuBarProps): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <BroadcastsSceneMenuBarInner {...props} /> : null
}

function BroadcastsSceneMenuBarInner({ currentTab }: BroadcastsSceneMenuBarProps): JSX.Element {
    const { startNewBroadcast } = useActions(newBroadcastAgentLogic)

    if (currentTab !== 'broadcasts' && currentTab !== 'calendar') {
        return (
            <MessagingTabSceneActions
                tab={currentTab}
                channelsUrl={urls.broadcasts('channels')}
                actions={[]}
                dataAttrKey={RESOURCE_TYPE}
            />
        )
    }

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-broadcast`,
            label: 'New broadcast',
            icon: <IconPlus />,
            disabledReason:
                getAccessControlDisabledReason(AccessControlResourceType.Workflow, AccessControlLevel.Editor) ??
                undefined,
            onSelect: startNewBroadcast,
            pinned: { order: 1, variant: 'primary', dataAttr: 'new-broadcast' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
