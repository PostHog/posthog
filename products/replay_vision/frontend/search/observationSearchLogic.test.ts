import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
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
    let suggestionsSpy: jest.Mock
    let viewedSpy: jest.Mock

    beforeEach(() => {
        localStorage.clear()
        searchSpy = jest.fn(() => [200, { results: [{ observation: { id: 'obs-1' }, distance: 0.1 }] }])
        suggestionsSpy = jest.fn(() => [200, { queries: ['coupon rejected at checkout'] }])
        viewedSpy = jest.fn(() => [204, null])
        useMocks({
            get: {
                '/api/projects/:team/vision/observations/search/': searchSpy,
                '/api/projects/:team/vision/observations/search_suggestions/': suggestionsSpy,
            },
            post: {
                '/api/projects/:team/vision/observations/search_viewed/': viewedSpy,
            },
        })
        initKeaTests()
    })

    it.each([
        ['a scanner-scoped', 'scanner-1', 'scanner-1'],
        ['a cross-scanner', null, null],
    ])('%s search sends the right scope and stores ranked results', async (_name, scannerId, expectedScope) => {
        const logic = observationSearchLogic({ scannerId, teamId: 1, userId: 'user-1' })
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
        const logic = observationSearchLogic({ scannerId: null, teamId: 1, userId: 'user-1' })
        logic.mount()
        logic.actions.searchSuccess(searchResults(distances), 'query', false)

        expect(logic.values.strongMatchDistanceCutoff).toEqual(expectedCutoff)
        logic.unmount()
    })

    it('a blank query never reaches the API', async () => {
        const logic = observationSearchLogic({ scannerId: null, teamId: 1, userId: 'user-1' })
        logic.mount()
        logic.actions.setQuery('   ')
        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()

        expect(searchSpy).not.toHaveBeenCalled()
        expect(logic.values.searching).toBe(false)
        logic.unmount()
    })

    it('a deep-linked q runs the search once, not on every navigation', async () => {
        const logic = observationSearchLogic({ scannerId: null, teamId: 1, userId: 'user-1' })
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
        const logic = observationSearchLogic({ scannerId: null, teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search' })
        logic.actions.setQuery('rage clicks ')
        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()

        expect(searchSpy).toHaveBeenCalledTimes(1)
        logic.unmount()
    })

    it('a failed deep-linked search does not re-fire on unrelated URL changes', async () => {
        searchSpy.mockImplementation(() => [500, { detail: 'embedding service down' }])
        const logic = observationSearchLogic({ scannerId: null, teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search', q: 'rage clicks' })
        await expectLogic(logic).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(1)

        router.actions.push(urls.replayVision(), { tab: 'search', q: 'rage clicks', unrelated: '1' })
        await expectLogic(logic).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(1)
        logic.unmount()
    })

    it('an AI consent error points the user at the organization setting', async () => {
        searchSpy.mockImplementation(() => [400, { code: 'ai_data_processing_not_approved', detail: 'off' }])
        const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')
        const logic = observationSearchLogic({ scannerId: null, teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search' })
        logic.actions.setQuery('anything')
        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()
        expect(toastSpy).toHaveBeenCalledWith(
            expect.stringContaining('AI data processing'),
            expect.objectContaining({ button: expect.objectContaining({ label: 'Open settings' }) })
        )
        toastSpy.mockRestore()
        logic.unmount()
    })

    it('loads suggestions for the scope on mount', async () => {
        const logic = observationSearchLogic({ scannerId: 'scanner-1', teamId: 1, userId: 'user-1' })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(suggestionsSpy).toHaveBeenCalledTimes(1)
        expect(new URL(suggestionsSpy.mock.calls[0][0].request.url).searchParams.get('scanner_id')).toBe('scanner-1')
        expect(logic.values.suggestedQueries).toEqual(['coupon rejected at checkout'])
        // The view is recorded through a POST, so the read itself has no side effect.
        expect(viewedSpy).toHaveBeenCalledTimes(1)
        expect(await viewedSpy.mock.calls[0][0].request.json()).toEqual({ scanner_id: 'scanner-1' })
        logic.unmount()
    })

    it('remembers queries that found something, newest first, without duplicates, capped', async () => {
        const logic = observationSearchLogic({ scannerId: null, teamId: 1, userId: 'user-1' })
        logic.mount()
        for (const query of ['one', 'two', 'three', 'four', 'five', 'six', 'two']) {
            logic.actions.searchSuccess(searchResults([0.2]), query, false)
        }
        logic.actions.searchSuccess([], 'nothing', false)
        expect(logic.values.recentQueries).toEqual(['two', 'six', 'five', 'four', 'three'])
        logic.unmount()
    })

    it('emptying the input returns to the empty state and drops q from the URL', async () => {
        const logic = observationSearchLogic({ scannerId: null, teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search' })
        logic.actions.setQuery('rage clicks')
        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()
        expect(logic.values.results).not.toBeNull()
        expect(router.values.searchParams.q).toBe('rage clicks')
        logic.actions.setQuery('')
        expect(logic.values.results).toBeNull()
        expect(logic.values.searchedQuery).toBeNull()
        expect(router.values.searchParams.q).toBeUndefined()
        logic.unmount()
    })

    it('a URL without q after a search shows the empty state instead of the old results', async () => {
        const logic = observationSearchLogic({ scannerId: null, teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search', q: 'rage clicks' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.results).not.toBeNull()
        router.actions.push(urls.replayVision(), { tab: 'search' })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.results).toBeNull()
        expect(searchSpy).toHaveBeenCalledTimes(1)
        logic.unmount()
    })
})
