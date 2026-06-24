import { actions, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { urls } from 'scenes/urls'

import { Breadcrumb } from '~/types'

import type { replayScannerSceneLogicType } from './replayScannerSceneLogicType'

export type ReplayScannerTab = 'observations' | 'on-demand' | 'configuration' | 'actions'

const SCANNER_TABS: ReplayScannerTab[] = ['observations', 'on-demand', 'configuration', 'actions']
const DEFAULT_TAB: ReplayScannerTab = 'observations'

function parseTab(tab: unknown): ReplayScannerTab {
    return SCANNER_TABS.includes(tab as ReplayScannerTab) ? (tab as ReplayScannerTab) : DEFAULT_TAB
}

export const replayScannerSceneLogic = kea<replayScannerSceneLogicType>([
    path(['products', 'replay_vision', 'frontend', 'replay_scanners', 'replayScannerSceneLogic']),

    actions({
        setScannerId: (scannerId: string) => ({ scannerId }),
        setActiveTab: (tab: ReplayScannerTab) => ({ tab }),
    }),

    reducers({
        scannerId: [
            'new' as string,
            {
                setScannerId: (_, { scannerId }) => scannerId,
            },
        ],
        activeTab: [
            DEFAULT_TAB as ReplayScannerTab,
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

    actionToUrl(({ values }) => ({
        setActiveTab: () => {
            const searchParams = { ...router.values.searchParams }
            if (values.activeTab === DEFAULT_TAB) {
                delete searchParams.tab
            } else {
                searchParams.tab = values.activeTab
            }
            return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
        },
    })),

    urlToAction(({ actions, values }) => ({
        [urls.replayVision(':id')]: ({ id }, searchParams) => {
            const scannerId = id || 'new'
            if (scannerId !== values.scannerId) {
                actions.setScannerId(scannerId)
            }
            const tab = parseTab(searchParams.tab)
            if (tab !== values.activeTab) {
                actions.setActiveTab(tab)
            }
        },
    })),
])
