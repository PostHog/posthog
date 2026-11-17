import { IconPlus } from '@posthog/icons'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

const RESOURCE_TYPE = 'uptime-monitoring'

export function UptimeMonitoringSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <UptimeMonitoringSceneMenuBarInner /> : null
}

function UptimeMonitoringSceneMenuBarInner(): JSX.Element {
    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-monitor`,
            label: 'New monitor',
            icon: <IconPlus />,
            disabledReason: 'Creating monitors is not available yet',
            onSelect: () => {},
            pinned: { order: 1, variant: 'primary', dataAttr: 'uptime-monitoring-new-monitor' },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
