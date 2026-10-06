import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ObservationSearchResultApi, ReplayObservationApi } from '../generated/api.schemas'
import { markSimilarSearchIntent } from './observationQueries'
import { SEARCH_COALESCE_MS, SEARCH_PAGE_SIZE, observationSearchLogic } from './observationSearchLogic'

function searchResults(distances: number[]): ObservationSearchResultApi[] {
    return distances.map(
        (distance, index) =>
            ({
                observation: { id: `obs-${index}` },
                distance,
            }) as unknown as ObservationSearchResultApi
    )
}

describe('observationSearchLogic', () => {
    let searchSpy: jest.Mock
    let suggestionsSpy: jest.Mock
    let viewedSpy: jest.Mock

    beforeEach(() => {
        localStorage.clear()
        sessionStorage.clear()
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
        userLogic.mount()
    })

    it.each([
        ['one scanner', 'scanner-1'],
        ['all scanners', null],
    ])('searching %s sends the scope from the URL and stores ranked results', async (_name, scannerId) => {
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search', scanner: scannerId ?? undefined })
        logic.actions.setQuery('confused users')
        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()

        expect(searchSpy).toHaveBeenCalledTimes(1)
        const requestUrl = new URL(searchSpy.mock.calls[0][0].request.url)
        expect(requestUrl.searchParams.get('q')).toBe('confused users')
        expect(requestUrl.searchParams.get('scanner_id')).toBe(scannerId)
        expect(logic.values.results?.map((r) => r.observation.id)).toEqual(['obs-1'])
        expect(router.values.searchParams.q).toBe('confused users')
        expect(router.values.searchParams.scanner).toBe(scannerId ?? undefined)

        await expectLogic(logic, () => logic.actions.setScannerId('scanner-2')).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(2)
        expect(new URL(searchSpy.mock.calls[1][0].request.url).searchParams.get('scanner_id')).toBe('scanner-2')

        router.actions.push(urls.replayVision(), { tab: 'search', scanner: 'scanner-3', q: 'rage clicks' })
        await expectLogic(logic).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(3)
        const lastRequest = new URL(searchSpy.mock.calls[2][0].request.url).searchParams
        expect([lastRequest.get('scanner_id'), lastRequest.get('q')]).toEqual(['scanner-3', 'rage clicks'])
        logic.unmount()
    })

    it.each([
        ['spread distances split off a top tier', [0.1, 0.12, 0.4], expect.closeTo(0.15)],
        ['clustered distances stay one tier', [0.1, 0.12, 0.14], null],
    ])('%s', (_name, distances, expectedCutoff) => {
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        logic.actions.searchSuccess(searchResults(distances), 'query', false)

        expect(logic.values.topMatchDistanceCutoff).toEqual(expectedCutoff)
        logic.unmount()
    })

    it.each([
        ['a full page plus one leaves a single result on page 2', SEARCH_PAGE_SIZE + 1, 2, [`obs-${SEARCH_PAGE_SIZE}`]],
        ['an exact page fill has no second page', SEARCH_PAGE_SIZE, 1, []],
    ])('%s', async (_name, resultCount, expectedPageCount, expectedSecondPageIds) => {
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        logic.actions.setPage(3)
        logic.actions.searchSuccess(searchResults(Array.from({ length: resultCount }, () => 0.1)), 'query', false)

        expect(logic.values.page).toBe(1)
        expect(logic.values.pageCount).toBe(expectedPageCount)
        expect(logic.values.pageResults).toHaveLength(Math.min(resultCount, SEARCH_PAGE_SIZE))
        await expectLogic(logic, () => logic.actions.setPage(2)).toFinishAllListeners()
        expect(logic.values.pageResults.map((r) => r.observation.id)).toEqual(expectedSecondPageIds)
        // Paging slices the one ranked response, so a page change must not re-embed and re-rank.
        expect(searchSpy).not.toHaveBeenCalled()
        logic.unmount()
    })

    it('a blank query never reaches the API', async () => {
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        logic.actions.setQuery('   ')
        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()

        expect(searchSpy).not.toHaveBeenCalled()
        expect(logic.values.searching).toBe(false)
        logic.unmount()
    })

    it('a deep-linked q runs the search once, not on every navigation', async () => {
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), {
            tab: 'search',
            q: 'rage clicks',
        })
        await expectLogic(logic).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(1)

        router.actions.push(urls.replayVision(), {
            tab: 'search',
            q: 'rage clicks',
        })
        await expectLogic(logic).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(1)
        logic.unmount()
    })

    it('a query with trailing whitespace searches once, despite the trimmed actionToUrl echo', async () => {
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search' })
        logic.actions.setQuery('rage clicks ')
        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()

        expect(searchSpy).toHaveBeenCalledTimes(1)
        logic.unmount()
    })

    it('a failed deep-linked search does not re-fire on unrelated URL changes', async () => {
        searchSpy.mockImplementation(() => [500, { detail: 'embedding service down' }])
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), {
            tab: 'search',
            q: 'rage clicks',
        })
        await expectLogic(logic).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(1)

        router.actions.push(urls.replayVision(), {
            tab: 'search',
            q: 'rage clicks',
            unrelated: '1',
        })
        await expectLogic(logic).toFinishAllListeners()
        expect(searchSpy).toHaveBeenCalledTimes(1)
        logic.unmount()
    })

    it.each([
        ['a failed', () => [500, { detail: 'embedding service down' }], { succeeded: false, error_status: 500 }],
        ['a successful', undefined, { succeeded: true, result_count: 1 }],
    ])('%s search is captured, so the failure rate is measurable', async (_name, mockResponse, expected) => {
        if (mockResponse) {
            searchSpy.mockImplementation(mockResponse as () => any)
        }
        const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search' })
        logic.actions.setQuery('rage clicks')
        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()

        expect(captureSpy).toHaveBeenCalledWith(
            'replay vision observation search completed',
            expect.objectContaining({ ...expected, scope: 'cross-scanner' })
        )
        captureSpy.mockRestore()
        logic.unmount()
    })

    it('a superseded failure is dropped, so the rate counts only the searches a person waited for', async () => {
        let releaseFirst: () => void = () => {}
        const firstHeld = new Promise<void>((resolve) => (releaseFirst = resolve))
        searchSpy.mockImplementationOnce(async () => {
            await firstHeld
            return [500, { detail: 'embedding service down' }]
        })
        searchSpy.mockImplementation(() => [500, { detail: 'embedding service down' }])
        const captureSpy = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined as any)
        const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search' })

        logic.actions.setQuery('rage clicks')
        logic.actions.search()
        await new Promise((resolve) => setTimeout(resolve, SEARCH_COALESCE_MS + 1))
        logic.actions.setQuery('coupon rejected at checkout')
        logic.actions.search()
        releaseFirst()
        await expectLogic(logic).toFinishAllListeners()

        expect(searchSpy).toHaveBeenCalledTimes(2)
        const outcomes = captureSpy.mock.calls.filter(
            ([event]) => event === 'replay vision observation search completed'
        )
        expect(outcomes).toHaveLength(1)
        expect(outcomes[0][1]).toMatchObject({ succeeded: false, error_status: 500 })
        expect(toastSpy).toHaveBeenCalledTimes(1)
        captureSpy.mockRestore()
        toastSpy.mockRestore()
        logic.unmount()
    })

    it('an AI consent error points the user at the organization setting', async () => {
        searchSpy.mockImplementation(() => [400, { code: 'ai_data_processing_not_approved', detail: 'off' }])
        const toastSpy = jest.spyOn(lemonToast, 'error').mockImplementation(() => 'toast-id')
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
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

    it('loads suggestions for the scope, and a deep link into a scope records one view, not two', async () => {
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search', scanner: 'scanner-1' })
        await expectLogic(logic).toFinishAllListeners()
        expect(suggestionsSpy).toHaveBeenCalledTimes(1)
        expect(new URL(suggestionsSpy.mock.calls[0][0].request.url).searchParams.get('scanner_id')).toBe('scanner-1')
        expect(logic.values.suggestedQueries).toEqual(['coupon rejected at checkout'])
        expect(viewedSpy).toHaveBeenCalledTimes(1)
        expect(await viewedSpy.mock.calls[0][0].request.json()).toEqual({ scanner_id: 'scanner-1' })

        await expectLogic(logic, () => logic.actions.setScannerId(null)).toFinishAllListeners()
        expect(suggestionsSpy).toHaveBeenCalledTimes(2)
        expect(new URL(suggestionsSpy.mock.calls[1][0].request.url).searchParams.get('scanner_id')).toBeNull()
        logic.unmount()
    })

    it('remembers queries that found something, newest first, without duplicates, capped', async () => {
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        for (const query of ['one', 'two', 'three', 'four', 'five', 'six', 'two']) {
            logic.actions.searchSuccess(searchResults([0.2]), query, false)
        }
        logic.actions.searchSuccess([], 'nothing', false)
        expect(logic.values.recentQueries).toEqual(['two', 'six', 'five'])
        logic.unmount()
    })

    it('emptying the input returns to the empty state and drops q from the URL', async () => {
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
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

    it('a "find similar" hand-off searches without the prose in the URL or recents, minus its source', async () => {
        searchSpy.mockImplementation(() => [
            200,
            {
                results: [
                    { observation: { id: 'obs-0' }, distance: 0 },
                    { observation: { id: 'obs-1' }, distance: 0.2 },
                ],
            },
        ])
        markSimilarSearchIntent({
            id: 'obs-0',
            scanner_result: { model_output: { summary: 'Stalled at checkout' } },
        } as unknown as ReplayObservationApi)
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
        logic.mount()
        router.actions.push(urls.replayVision(), { tab: 'search', similar: 'obs-0', scanner: 'scanner-2' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.results?.map((r) => r.observation.id)).toEqual(['obs-1'])
        expect(router.values.searchParams.q).toBeUndefined()
        expect(logic.values.recentQueries).toEqual([])
        expect(searchSpy).toHaveBeenCalledTimes(1)
        expect(new URL(searchSpy.mock.calls[0][0].request.url).searchParams.get('scanner_id')).toBe('scanner-2')

        // Editing the prose keeps the shown results' provenance until the edited search lands as a regular one.
        logic.actions.setQuery('Stalled at checkout twice')
        expect(logic.values.sourceObservationId).toBe('obs-0')
        router.actions.push(urls.replayVision(), { tab: 'search', similar: 'obs-0', scanner: 'scanner-2', t: 12 })
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.query).toBe('Stalled at checkout twice')
        expect(searchSpy).toHaveBeenCalledTimes(1)

        await expectLogic(logic, () => logic.actions.search()).toFinishAllListeners()
        expect(logic.values.sourceObservationId).toBeNull()
        expect(router.values.searchParams.q).toBe('Stalled at checkout twice')
        expect(logic.values.recentQueries).toEqual(['Stalled at checkout twice'])

        router.actions.push(urls.replayVision(), { tab: 'search', similar: 'obs-9', scanner: 'scanner-2' })
        await expectLogic(logic).toFinishAllListeners()
        expect(router.values.searchParams.similar).toBeUndefined()
        expect(router.values.searchParams.q).toBeUndefined()
        expect(logic.values.results).toBeNull()
        expect(searchSpy).toHaveBeenCalledTimes(2)
        logic.unmount()
    })

    it('a URL without q after a search shows the empty state instead of the old results', async () => {
        const logic = observationSearchLogic({ teamId: 1, userId: 'user-1' })
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
