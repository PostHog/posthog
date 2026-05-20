import { actions, kea, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { replayLensSceneLogicType } from './replayLensSceneLogicType'
import { ALL_EDITOR_TABS, EditorTab } from './types'

export interface ReplayLensSceneLogicProps {
    tabId: string
}

export const replayLensSceneLogic = kea<replayLensSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_lenses', 'replayLensSceneLogic']),
    props({} as ReplayLensSceneLogicProps),
    tabAwareScene(),

    actions({
        setLensId: (lensId: string) => ({ lensId }),
        setActiveTab: (tab: EditorTab) => ({ tab }),
    }),

    reducers({
        lensId: [
            'new' as string,
            {
                setLensId: (_, { lensId }) => lensId,
            },
        ],
        activeTab: [
            'configuration' as EditorTab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),

    selectors({
        breadcrumbs: [
            (s) => [s.lensId],
            (lensId: string): Breadcrumb[] => [
                {
                    key: 'replay-vision',
                    name: 'Replay vision',
                    path: urls.replayVision(),
                    iconType: 'replay_vision',
                },
                {
                    key: lensId === 'new' ? 'new-lens' : `lens-${lensId}`,
                    name: lensId === 'new' ? 'New lens' : 'Lens',
                    path: urls.replayVision(lensId),
                },
            ],
        ],
    }),

    tabAwareActionToUrl(({ values }) => ({
        setActiveTab: () => {
            const defaultTab: EditorTab = values.lensId === 'new' ? 'configuration' : 'observations'
            const tab = values.activeTab === defaultTab ? undefined : values.activeTab
            return [
                urls.replayVision(values.lensId),
                { ...router.values.searchParams, tab },
                undefined,
                { replace: true },
            ]
        },
    })),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.replayVision(':id')]: ({ id }, searchParams) => {
            const lensId = id || 'new'
            if (lensId !== values.lensId) {
                actions.setLensId(lensId)
            }
            const raw = typeof searchParams.tab === 'string' ? searchParams.tab : ''
            const defaultTab: EditorTab = lensId === 'new' ? 'configuration' : 'observations'
            const tab: EditorTab = (ALL_EDITOR_TABS as string[]).includes(raw) ? (raw as EditorTab) : defaultTab
            if (tab !== values.activeTab) {
                actions.setActiveTab(tab)
            }
        },
    })),
])
