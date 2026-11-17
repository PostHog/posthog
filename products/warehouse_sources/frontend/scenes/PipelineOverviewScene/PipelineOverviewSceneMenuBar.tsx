import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconPlusSmall, IconRefresh } from '@posthog/icons'
import { Button } from '@posthog/quill'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { urls } from 'scenes/urls'

import type { SceneAction } from '~/layout/scenes/sceneActions/sceneActionModel'
import { SceneActions } from '~/layout/scenes/sceneActions/SceneActions'

import { pipelineOverviewSceneLogic } from './pipelineOverviewSceneLogic'

const RESOURCE_TYPE = 'etl'

export function PipelineOverviewSceneMenuBar(): JSX.Element | null {
    const enabled = useFeatureFlag('SCENE_MENU_BAR')
    return enabled ? <PipelineOverviewSceneMenuBarInner /> : null
}

function PipelineOverviewSceneMenuBarInner(): JSX.Element {
    const { jobStatsLoading } = useValues(pipelineOverviewSceneLogic)
    const { refresh } = useActions(pipelineOverviewSceneLogic)

    const actions: SceneAction[] = [
        {
            group: 'file',
            section: 'create',
            id: `${RESOURCE_TYPE}-menubar-new-source`,
            label: 'New source',
            icon: <IconPlusSmall />,
            onSelect: () => router.actions.push(urls.dataPipelinesNew('source')),
            pinned: { order: 1, variant: 'primary', dataAttr: 'etl-new-source' },
        },
        {
            group: 'file',
            section: 'refresh',
            id: `${RESOURCE_TYPE}-menubar-refresh`,
            label: 'Refresh',
            icon: <IconRefresh />,
            disabledReason: jobStatsLoading ? 'Refreshing' : undefined,
            onSelect: refresh,
            pinned: {
                order: 2,
                variant: 'secondary',
                render: () => (
                    <Button variant="outline" onClick={refresh} loading={jobStatsLoading} data-attr="etl-refresh">
                        <IconRefresh />
                        Refresh
                    </Button>
                ),
            },
        },
    ]

    return <SceneActions actions={actions} dataAttrKey={RESOURCE_TYPE} />
}
