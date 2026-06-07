import { actions, kea, path, props, reducers, selectors } from 'kea'
import { router, urlToAction } from 'kea-router'

import { trackedActionToUrl } from 'lib/logic/scenes/trackedActionToUrl'
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

    actions({
        setScannerId: (scannerId: string) => ({ scannerId }),
        setActiveTab: (tab: EditorTab) => ({ tab }),
        setTemplateKey: (templateKey: string | null) => ({ templateKey }),
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
        templateKey: [
            null as string | null,
            {
                setTemplateKey: (_, { templateKey }) => templateKey,
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

    trackedActionToUrl(({ values }) => ({
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

    urlToAction(({ actions, values }) => ({
        [urls.replayVision(':id')]: ({ id }, searchParams) => {
            const scannerId = id || 'new'
            if (scannerId !== values.scannerId) {
                actions.setScannerId(scannerId)
            }
            const templateKey =
                scannerId === 'new' && typeof searchParams.template === 'string' ? searchParams.template : null
            if (templateKey !== values.templateKey) {
                actions.setTemplateKey(templateKey)
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
