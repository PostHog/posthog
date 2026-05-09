import { actions, kea, path, props, reducers } from 'kea'
import { router } from 'kea-router'

import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { urls } from 'scenes/urls'

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

    tabAwareActionToUrl(({ values }) => ({
        setActiveTab: () => {
            const tab = values.activeTab === 'configuration' ? undefined : values.activeTab
            return [
                urls.replayLens(values.lensId),
                { ...router.values.searchParams, tab },
                undefined,
                { replace: true },
            ]
        },
    })),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.replayLens(':id')]: ({ id }, searchParams) => {
            const lensId = id || 'new'
            if (lensId !== values.lensId) {
                actions.setLensId(lensId)
            }
            const raw = typeof searchParams.tab === 'string' ? searchParams.tab : ''
            const tab: EditorTab = (ALL_EDITOR_TABS as string[]).includes(raw) ? (raw as EditorTab) : 'configuration'
            if (tab !== values.activeTab) {
                actions.setActiveTab(tab)
            }
        },
    })),
])
