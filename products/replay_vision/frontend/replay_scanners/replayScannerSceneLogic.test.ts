import { router } from 'kea-router'

import { urls } from 'scenes/urls'

import { initKeaTests } from '~/test/init'

import { ReplayScannerTab, replayScannerSceneLogic } from './replayScannerSceneLogic'

describe('replayScannerSceneLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it.each([
        [
            'a scanner and its query',
            'scanner-9',
            { q: 'rage clicks' },
            { tab: 'search', scanner: 'scanner-9', q: 'rage clicks' },
        ],
        ['no scanner for a new one', 'new', {}, { tab: 'search' }],
    ])(
        'an old per-scanner search link with %s opens the hub search and keeps the hash',
        (_name, id, extra, expected) => {
            const logic = replayScannerSceneLogic()
            logic.mount()
            router.actions.push(urls.replayVision(id), { tab: 'search', ...extra }, { sessionRecordingId: 'session-1' })

            expect(router.values.location.pathname).toMatch(new RegExp(`${urls.replayVision()}$`))
            expect(router.values.searchParams).toEqual(expected)
            expect(router.values.hashParams).toEqual({ sessionRecordingId: 'session-1' })
            logic.unmount()
        }
    )

    it.each([
        ['on-demand', ReplayScannerTab.Run],
        ['backfills', ReplayScannerTab.Run],
        ['configuration', ReplayScannerTab.Overview],
    ])('an old %s tab link opens the tab it was merged into', (oldTab, expected) => {
        const logic = replayScannerSceneLogic()
        logic.mount()
        router.actions.push(urls.replayVision('scanner-9'), { tab: oldTab })

        expect(logic.values.activeTab).toBe(expected)
        logic.unmount()
    })
})
