import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ObservationSearchResultApi } from '../generated/api.schemas'
import { observationSearchLogic } from './observationSearchLogic'

function searchResults(distances: number[]): ObservationSearchResultApi[] {
    return distances.map(
        (distance, index) =>
            ({ observation: { id: `obs-${index}` }, distance }) as unknown as ObservationSearchResultApi
    )
}

describe('observationSearchLogic', () => {
    let searchSpy: jest.Mock

    beforeEach(() => {
        searchSpy = jest.fn(() => [200, { results: [{ observation: { id: 'obs-1' }, distance: 0.1 }] }])
        useMocks({
            get: {
                '/api/projects/:team/vision/observations/search/': searchSpy,
            },
        })
        initKeaTests()
    })

    it.each([
        ['a scanner-scoped', 'scanner-1', 'scanner-1'],
        ['a cross-scanner', null, null],
    ])('%s search sends the right scope and stores ranked results', async (_name, scannerId, expectedScope) => {
        const logic = observationSearchLogic({ scannerId })
        logic.mount()
        // On the live page URL, the actionToUrl echo would re-dispatch search without the in-flight guard.
        router.actions.push(scannerId ? urls.replayVision(scannerId) : urls.replayVision(), { tab: 'search' })
        logic.actions.setQuery('confused users')
        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()

        expect(searchSpy).toHaveBeenCalledTimes(1)
        const requestUrl = new URL(searchSpy.mock.calls[0][0].request.url)
        expect(requestUrl.searchParams.get('q')).toBe('confused users')
        expect(requestUrl.searchParams.get('scanner_id')).toBe(expectedScope)
        expect(logic.values.results?.map((r) => r.observation.id)).toEqual(['obs-1'])
        logic.unmount()
    })

    it.each([
        ['spread distances tag the top tier', [0.1, 0.12, 0.4], expect.closeTo(0.15)],
        ['clustered distances tag nothing', [0.1, 0.12, 0.14], null],
        ['a single result tags nothing', [0.2], null],
    ])('%s', (_name, distances, expectedCutoff) => {
        const logic = observationSearchLogic({ scannerId: null })
        logic.mount()
        logic.actions.searchSuccess(searchResults(distances), 'query', false)

        expect(logic.values.strongMatchDistanceCutoff).toEqual(expectedCutoff)
        logic.unmount()
    })

    it('a blank query never reaches the API', async () => {
        const logic = observationSearchLogic({ scannerId: null })
        logic.mount()
        logic.actions.setQuery('   ')
        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()

        expect(searchSpy).not.toHaveBeenCalled()
        expect(logic.values.searching).toBe(false)
        logic.unmount()
    })

    it('a deep-linked q runs the search once, not on every navigation', async () => {
        const logic = observationSearchLogic({ scannerId: null })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search', q: 'rage clicks' })
        await expectLogic(logic).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(1)

        router.actions.push(urls.replayVision(), { tab: 'search', q: 'rage clicks' })
        await expectLogic(logic).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(1)
        logic.unmount()
    })

    it('a query with trailing whitespace searches once, despite the trimmed actionToUrl echo', async () => {
        const logic = observationSearchLogic({ scannerId: null })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search' })
        logic.actions.setQuery('rage clicks ')
        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()

        expect(searchSpy).toHaveBeenCalledTimes(1)
        logic.unmount()
    })

    it('a failed deep-linked search does not re-fire on unrelated URL changes', async () => {
        searchSpy.mockImplementation(() => [500, { detail: 'embedding service down' }])
        const logic = observationSearchLogic({ scannerId: null })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search', q: 'rage clicks' })
        await expectLogic(logic).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(1)

        router.actions.push(urls.replayVision(), { tab: 'search', q: 'rage clicks', unrelated: '1' })
        await expectLogic(logic).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(1)
        logic.unmount()
    })
})
