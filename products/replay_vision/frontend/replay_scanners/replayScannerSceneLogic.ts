import { actions, kea, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareScene } from 'lib/logic/scenes/tabAwareScene'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { replayScannerSceneLogicType } from './replayScannerSceneLogicType'
import { ALL_EDITOR_TABS, EditorTab } from './types'

export interface ReplayScannerSceneLogicProps {
    tabId: string
}

export const replayScannerSceneLogic = kea<replayScannerSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'replayScannerSceneLogic']),
    props({} as ReplayScannerSceneLogicProps),
    tabAwareScene(),

    actions({
        setScannerId: (scannerId: string) => ({ scannerId }),
        setActiveTab: (tab: EditorTab) => ({ tab }),
    }),

    reducers({
        scannerId: [
            'new' as string,
            {
                setScannerId: (_, { scannerId }) => scannerId,
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
            (s) => [s.scannerId],
            (scannerId: string): Breadcrumb[] => [
                {
                    key: 'replay-vision',
                    name: 'Replay vision',
                    path: urls.replayVision(),
                    iconType: 'replay_vision',
                },
                {
                    key: scannerId === 'new' ? 'new-scanner' : `scanner-${scannerId}`,
                    name: scannerId === 'new' ? 'New scanner' : 'Scanner',
                    path: urls.replayVision(scannerId),
                },
            ],
        ],
    }),

    tabAwareActionToUrl(({ values }) => ({
        setActiveTab: () => {
            const defaultTab: EditorTab = values.scannerId === 'new' ? 'configuration' : 'observations'
            const tab = values.activeTab === defaultTab ? undefined : values.activeTab
            return [
                urls.replayVision(values.scannerId),
                { ...router.values.searchParams, tab },
                undefined,
                { replace: true },
            ]
        },
    })),

    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.replayVision(':id')]: ({ id }, searchParams) => {
            const scannerId = id || 'new'
            if (scannerId !== values.scannerId) {
                actions.setScannerId(scannerId)
            }
            const raw = typeof searchParams.tab === 'string' ? searchParams.tab : ''
            const defaultTab: EditorTab = scannerId === 'new' ? 'configuration' : 'observations'
            const tab: EditorTab = (ALL_EDITOR_TABS as string[]).includes(raw) ? (raw as EditorTab) : defaultTab
            if (tab !== values.activeTab) {
                actions.setActiveTab(tab)
            }
        },
    })),
])
