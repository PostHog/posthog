import { MOCK_DEFAULT_TEAM } from '~/lib/api.mock'

/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ScratchpadEntryApi } from 'products/signals/frontend/generated/api.schemas'

import {
    SCRATCHPAD_FETCH_LIMIT,
    SCRATCHPAD_PREVIEW_CHARS,
    describeLoadedSpan,
    scratchpadLogic,
} from './scratchpadLogic'

const SCRATCHPAD_URL = '/api/projects/:team_id/signals/scout/scratchpad/'

const entry = (key: string, content: string): ScratchpadEntryApi =>
    ({
        key,
        content,
        created_at: '2026-07-01T00:00:00Z',
        updated_at: '2026-07-02T00:00:00Z',
    }) as ScratchpadEntryApi

// A body that fills the preview window exactly is what a truncated note looks like on the wire —
// the API slices without leaving a marker.
const TRUNCATED = entry('pattern:long', 'x'.repeat(SCRATCHPAD_PREVIEW_CHARS))
const ALSO_TRUNCATED = entry('pattern:also-long', 'y'.repeat(SCRATCHPAD_PREVIEW_CHARS))
const WHOLE = entry('pattern:short', 'a short note')
const fullBodyFor = (key: string): string => `${key} full body, tail included`

describe('scratchpadLogic', () => {
    let logic: ReturnType<typeof scratchpadLogic.build>
    let searchRequests: URLSearchParams[]

    beforeEach(async () => {
        searchRequests = []
        useMocks({
            get: {
                [SCRATCHPAD_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    searchRequests.push(params)
                    // The expand-time lookup is an exact `key` match; everything else is the list read.
                    const key = params.get('key')
                    if (key) {
                        return [200, [entry(key, fullBodyFor(key))]]
                    }
                    return [200, [TRUNCATED, ALSO_TRUNCATED, WHOLE]]
                },
            },
        })
        initKeaTests()
        logic = scratchpadLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        searchRequests = []
    })

    afterEach(() => {
        logic.unmount()
    })

    it('asks for previews rather than full bodies on the list read', async () => {
        logic.unmount()
        searchRequests = []
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(searchRequests[0].get('content_max_chars')).toEqual(String(SCRATCHPAD_PREVIEW_CHARS))
    })

    it('fetches the full body by exact key when a truncated entry is expanded', async () => {
        logic.actions.toggleEntry(TRUNCATED.key)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.fullContentByKey[TRUNCATED.key]).toEqual(fullBodyFor(TRUNCATED.key))
        expect(logic.values.loadingContentKeys).toEqual([])
        // Not `text`: that is an ILIKE over key and content, so entries merely quoting this key
        // can crowd the row we asked for out of the window.
        expect(searchRequests[0].get('key')).toEqual(TRUNCATED.key)
        expect(searchRequests[0].get('text')).toBeNull()
    })

    // A shared per-action breakpoint would unwind the first request when the second starts,
    // leaving the first key stuck in `loadingContentKeys` behind a skeleton forever — and
    // `toggleEntry` skips keys already loading, so it could never recover.
    it('resolves both bodies when two notes are expanded back to back', async () => {
        logic.actions.toggleEntry(TRUNCATED.key)
        logic.actions.toggleEntry(ALSO_TRUNCATED.key)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.fullContentByKey).toEqual({
            [TRUNCATED.key]: fullBodyFor(TRUNCATED.key),
            [ALSO_TRUNCATED.key]: fullBodyFor(ALSO_TRUNCATED.key),
        })
        expect(logic.values.loadingContentKeys).toEqual([])
    })

    // The whole point of the preview projection is that opening a note that already arrived
    // complete costs nothing. Dropping the truncation guard would put a request behind every
    // expand — the regression this change exists to avoid.
    it.each([
        ['an entry that arrived whole', WHOLE.key, false],
        ['a truncated entry', TRUNCATED.key, true],
    ])('expanding %s issues a lookup: %s', async (_name, key, expectedRequest) => {
        logic.actions.toggleEntry(key)
        await expectLogic(logic).toFinishAllListeners()

        expect(searchRequests.length).toEqual(expectedRequest ? 1 : 0)
    })

    it('does not re-fetch a body it already has, or fetch on collapse', async () => {
        logic.actions.toggleEntry(TRUNCATED.key)
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.toggleEntry(TRUNCATED.key)
        logic.actions.toggleEntry(TRUNCATED.key)
        await expectLogic(logic).toFinishAllListeners()

        expect(searchRequests.length).toEqual(1)
        expect(logic.values.expandedKeys).toEqual([TRUNCATED.key])
    })

    // The roster's "learned" count and the scout page's memory panel read `entries`; a fleet search
    // must land somewhere else or it silently shrinks a scout's memory until the next reload.
    it('keeps the unfiltered window intact while a search runs', async () => {
        useMocks({
            get: {
                [SCRATCHPAD_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    searchRequests.push(params)
                    return [200, params.get('text') ? [WHOLE] : [TRUNCATED, ALSO_TRUNCATED, WHOLE]]
                },
            },
        })

        logic.actions.setSearchText('short')
        await expectLogic(logic).toFinishAllListeners()

        expect(searchRequests.map((params) => params.get('text'))).toEqual(['short'])
        expect(logic.values.entries).toHaveLength(3)
        expect(logic.values.searchResults).toEqual([WHOLE])
        expect(logic.values.visibleEntries).toEqual([WHOLE])

        logic.actions.setSearchText('')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.searchResults).toBeNull()
        expect(logic.values.visibleEntries).toHaveLength(3)
        // Clearing the box needs no request: the window never went anywhere.
        expect(searchRequests).toHaveLength(1)
    })

    it('flags the learned count as capped only when a full fetch all falls inside the window', () => {
        const fresh = (i: number): ScratchpadEntryApi => ({
            ...entry(`pattern:${i}`, 'note'),
            updated_at: new Date().toISOString(),
        })
        const full = Array.from({ length: SCRATCHPAD_FETCH_LIMIT }, (_, i) => fresh(i))

        logic.actions.loadEntriesSuccess(full)
        expect(logic.values.recentlyLearnedCount).toBe(SCRATCHPAD_FETCH_LIMIT)
        expect(logic.values.recentlyLearnedCountCapped).toBe(true)

        // One stale entry in a full fetch means the window ended inside it, so the count is exact.
        logic.actions.loadEntriesSuccess([...full.slice(1), WHOLE])
        expect(logic.values.recentlyLearnedCount).toBe(SCRATCHPAD_FETCH_LIMIT - 1)
        expect(logic.values.recentlyLearnedCountCapped).toBe(false)

        logic.actions.loadEntriesSuccess(full.slice(0, 10))
        expect(logic.values.recentlyLearnedCountCapped).toBe(false)
    })

    // Ledger filters narrow what is listed and nothing else. The roster's "learned" count and the
    // scout page's memory panel read `entries`, so a filter that reached them would silently shrink
    // numbers the reader never asked about.
    it('combines the client-side filters and leaves the loaded window intact', async () => {
        const rows = [
            { ...entry('pattern:apm:p95', 'note'), created_by_skill: 'signals-scout-apm' },
            { ...entry('baseline:apm:error-rate', 'note'), created_by_skill: 'signals-scout-apm' },
            { ...entry('pattern:logs:redis', 'note'), created_by_skill: 'signals-scout-logs' },
            { ...entry('dedupe:apm:34316', 'note'), created_by_skill: 'signals-scout-apm' },
        ]
        logic.actions.loadEntriesSuccess(rows)

        logic.actions.setScoutFilter(['signals-scout-apm'])
        expect(logic.values.filteredEntries?.map((e) => e.key)).toEqual([
            'pattern:apm:p95',
            'baseline:apm:error-rate',
            'dedupe:apm:34316',
        ])

        logic.actions.setKindFilter(['pattern', 'baseline'])
        expect(logic.values.filteredEntries?.map((e) => e.key)).toEqual(['pattern:apm:p95', 'baseline:apm:error-rate'])
        // The footer prints the bookkeeping count as a share of the listed rows, so a count taken
        // before the facet filters can exceed the number of rows it describes.
        expect(logic.values.visibleBookkeepingCount).toBe(0)

        logic.actions.setTopicFilter(['logs'])
        expect(logic.values.filteredEntries).toEqual([])
        expect(logic.values.entries).toHaveLength(4)

        logic.actions.clearFilters()
        expect(logic.values.filteredEntries).toHaveLength(4)
        expect(logic.values.hasActiveFilters).toBe(false)
    })

    // The span is the only filter the endpoint applies, so clearing has to refetch. Resetting the
    // control alone leaves a narrowed response on screen with no filter shown, and an empty
    // narrowed window then reads as a project whose scouts have written nothing.
    it('refetches the full window when the filters are cleared', async () => {
        logic.actions.setTimeFilter('1h')
        await expectLogic(logic).toFinishAllListeners()
        expect(searchRequests.map((params) => params.get('date_from') !== null)).toEqual([true])

        searchRequests = []
        logic.actions.clearFilters()
        await expectLogic(logic).toFinishAllListeners()
        expect(searchRequests.map((params) => params.get('date_from'))).toEqual([null])
    })

    // Report-pipeline stages write to this keyspace under a `pipeline:` identity. The ledger's
    // Scout column already calls them what they are, so counting them as scouts would make the
    // header claim more scouts than wrote.
    it('leaves the pipeline writers out of the scouts stat', async () => {
        logic.actions.loadEntriesSuccess([
            { ...entry('pattern:apm:p95', 'note'), created_by_skill: 'signals-scout-apm' },
            { ...entry('baseline:apm:error-rate', 'note'), created_by_skill: 'signals-scout-apm' },
            { ...entry('judged:report-1', 'note'), created_by_skill: 'pipeline:report-research' },
            { ...entry('watchlist:manual', 'note'), created_by_skill: null },
        ])

        expect(logic.values.windowStats.scouts).toBe(1)
    })

    // The bookkeeping kinds outnumber the durable knowledge, which is the whole reason the switch
    // exists. A key whose prefix is not a known kind is a topic, not a kind, and must survive it.
    it('drops only the bookkeeping kinds when the switch is on', async () => {
        logic.actions.loadEntriesSuccess([
            entry('pattern:apm:p95', 'note'),
            entry('judged:report-1', 'note'),
            entry('dedupe:apm:34316', 'note'),
            entry('billing_spikes:34302', 'note'),
        ])

        logic.actions.setHideBookkeeping(true)
        expect(logic.values.filteredEntries?.map((e) => e.key)).toEqual(['pattern:apm:p95', 'billing_spikes:34302'])
        expect(logic.values.visibleBookkeepingCount).toBe(2)

        logic.actions.setHideBookkeeping(false)
        expect(logic.values.filteredEntries).toHaveLength(4)

        // The switch counts towards `hasActiveFilters`, which is what renders the clear button, so
        // a clear that spares it promises rows it does not bring back. A window of nothing but
        // bookkeeping rows then renders the same empty state after every press.
        logic.actions.setHideBookkeeping(true)
        logic.actions.clearFilters()
        expect(logic.values.hideBookkeeping).toBe(false)
        expect(logic.values.filteredEntries).toHaveLength(4)
        expect(logic.values.hasActiveFilters).toBe(false)
    })

    // kea-loaders leaves `entries` at its prior value on failure, so a failed reload keeps rows on
    // screen that answer the span the reader had before. The flag is the only thing that can tell
    // the panel to say so, instead of presenting those rows as the answer to the new span.
    it('keeps the loaded rows and records the failure when a reload rejects', async () => {
        logic.actions.loadEntriesSuccess([TRUNCATED, WHOLE])
        useMocks({ get: { [SCRATCHPAD_URL]: () => [500, {}] } })

        logic.actions.setTimeFilter('1h')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.loadFailed).toBe(true)
        expect(logic.values.entries).toEqual([TRUNCATED, WHOLE])
        expect(logic.values.filteredEntries).toHaveLength(2)
    })

    // A wider span is the slower read, so narrowing the span right after widening it is the order
    // that lets the older response answer last. If it lands, the ledger and the header describe a
    // span the select does not name, and re-picking that span fires nothing.
    it('drops a window response that a newer span superseded', async () => {
        const stale = entry('pattern:stale-span', 'note')
        let narrowServed = (): void => {}
        const narrowRequestServed = new Promise<void>((resolve) => {
            narrowServed = resolve
        })
        let listRequests = 0
        useMocks({
            get: {
                [SCRATCHPAD_URL]: async () => {
                    listRequests += 1
                    // The wide request answers only once the narrow one that superseded it has.
                    if (listRequests === 1) {
                        await narrowRequestServed
                        return [200, [stale]]
                    }
                    narrowServed()
                    return [200, [WHOLE]]
                },
            },
        })

        logic.actions.setTimeFilter('30d')
        logic.actions.setTimeFilter('1h')
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.entries).toEqual([WHOLE])
    })

    // Older pages walk the unfiltered window with a cursor, and a search is a separate one-shot
    // read they never reach. A control offered during a search spends a page of up to a thousand
    // rows the table cannot show, and moves the header counts while the listed rows stay put.
    it('offers no older pages while a search is active', async () => {
        logic.actions.loadEntriesSuccess(
            Array.from({ length: SCRATCHPAD_FETCH_LIMIT }, (_, i) => entry(`pattern:${i}`, 'note'))
        )
        expect(logic.values.canLoadOlderEntries).toBe(true)

        logic.actions.setSearchText('redis')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.canLoadOlderEntries).toBe(false)

        logic.actions.setSearchText('')
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.canLoadOlderEntries).toBe(true)
    })

    // A reload drops the walked pages, and the fresh first page has not yet said whether anything
    // older is left. A control left live over that gap pages from the window that just went away.
    it('retires the older-page control while the first page reloads', async () => {
        logic.actions.loadEntriesSuccess(
            Array.from({ length: SCRATCHPAD_FETCH_LIMIT }, (_, i) => entry(`pattern:${i}`, 'note'))
        )
        expect(logic.values.hasMoreOlderEntries).toBe(true)

        logic.actions.loadEntries()
        expect(logic.values.hasMoreOlderEntries).toBe(false)

        // The fresh first page decides it again, and this one came back short.
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.hasMoreOlderEntries).toBe(false)
    })

    // A page read against a window that a reload replaced has nothing to attach to. Appending it
    // files old rows under a new first page, and its dedupe set cannot see that page's keys, so a
    // key can render twice in a table that keys rows by it.
    it('drops an older page that answers after the first page reloaded', async () => {
        const older = { ...entry('pattern:older', 'note'), updated_at: '2026-06-01T00:00:00Z' }
        let firstPageServed = (): void => {}
        const reloadServed = new Promise<void>((resolve) => {
            firstPageServed = resolve
        })
        useMocks({
            get: {
                [SCRATCHPAD_URL]: async ({ request }) => {
                    const params = new URL(request.url).searchParams
                    // The walked page answers only once the reload that invalidated it has.
                    if (params.get('date_to')) {
                        await reloadServed
                        return [200, [older]]
                    }
                    firstPageServed()
                    return [200, [ALSO_TRUNCATED]]
                },
            },
        })

        logic.actions.loadEntriesSuccess([TRUNCATED, WHOLE])
        logic.actions.loadOlderEntries()
        logic.actions.loadEntries()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.windowEntries).toEqual([ALSO_TRUNCATED])
    })

    // The older-page request is the panel's heaviest, so a timeout or a 5xx is its likely end, and
    // a page that succeeds can append nothing too once the dedupe drops it. Without a flag the
    // spinner just stops, and the reader reads a failed press as an empty memory.
    it('records a failed older page and clears the record on the retry', async () => {
        logic.actions.loadEntriesSuccess(
            Array.from({ length: SCRATCHPAD_FETCH_LIMIT }, (_, i) => entry(`pattern:${i}`, 'note'))
        )
        useMocks({ get: { [SCRATCHPAD_URL]: () => [500, {}] } })

        logic.actions.loadOlderEntries()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.olderEntriesFailed).toBe(true)
        expect(logic.values.olderEntriesLoading).toBe(false)
        // The control stays, so the press can be repeated.
        expect(logic.values.canLoadOlderEntries).toBe(true)

        useMocks({ get: { [SCRATCHPAD_URL]: () => [200, []] } })
        logic.actions.loadOlderEntries()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.olderEntriesFailed).toBe(false)
    })

    // Nothing older than the first page was reachable before: the endpoint caps at 1,000 rows and
    // the panel only ever asked once. The `date_to` bound is exclusive, but rows can share a
    // timestamp, so a page may still repeat a key already on screen.
    it('walks the date_to cursor for older entries and drops keys already loaded', async () => {
        const older = { ...entry('pattern:older', 'note'), updated_at: '2026-06-01T00:00:00Z' }
        useMocks({
            get: {
                [SCRATCHPAD_URL]: ({ request }) => {
                    const params = new URL(request.url).searchParams
                    searchRequests.push(params)
                    return [200, params.get('date_to') ? [WHOLE, older] : [TRUNCATED, WHOLE]]
                },
            },
        })
        logic.actions.loadEntries()
        await expectLogic(logic).toFinishAllListeners()
        searchRequests = []

        logic.actions.loadOlderEntries()
        await expectLogic(logic).toFinishAllListeners()

        expect(searchRequests[0].get('date_to')).toEqual(WHOLE.updated_at)
        expect(logic.values.olderEntries).toEqual([older])
        expect(logic.values.windowEntries?.map((e) => e.key)).toEqual([TRUNCATED.key, WHOLE.key, older.key])
        // A short page is the end of the memory, so the button goes away.
        expect(logic.values.hasMoreOlderEntries).toBe(false)
        // A fresh first page may already carry these rows, so the older pages are dropped with it.
        logic.actions.loadEntries()
        expect(logic.values.olderEntries).toEqual([])
    })

    // A key namespaced by a report UUID says nothing on its own, and the reports endpoint has no
    // bulk-by-id filter, so each title is one request — resolved once and cached.
    it('resolves report titles for UUID-namespaced keys exactly once', async () => {
        const reportId = '01a0918c-5f5f-74c4-b539-c634a8cb990a'
        let reportRequests = 0
        useMocks({
            get: {
                [SCRATCHPAD_URL]: () => [200, [entry(`judged:${reportId}`, 'note')]],
                '/api/projects/:team_id/signals/reports/:id/': () => {
                    reportRequests += 1
                    return [200, { id: reportId, title: 'Export error rate doubled' }]
                },
            },
        })

        logic.actions.loadEntries()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.reportTitles).toEqual({ [reportId]: 'Export error rate doubled' })
        expect(reportRequests).toBe(1)
        expect(logic.values.unresolvedReportIds).toEqual([])
    })

    // An id reaches `reportTitles` only when its response lands, so a pass that starts while
    // another is in flight lists the same ids again. Two loads answering at different times is
    // ordinary here, and the report detail read is one of the heaviest requests the product makes.
    it('does not re-request a report title a pass is already fetching', async () => {
        const reportId = '01a0918c-5f5f-74c4-b539-c634a8cb990a'
        let reportRequests = 0
        useMocks({
            get: {
                [SCRATCHPAD_URL]: () => [200, [entry(`judged:${reportId}`, 'note')]],
                '/api/projects/:team_id/signals/reports/:id/': () => {
                    reportRequests += 1
                    return [200, { id: reportId, title: 'Export error rate doubled' }]
                },
            },
        })

        logic.actions.loadEntriesSuccess([entry(`judged:${reportId}`, 'note')])
        // An older page landing while the first pass is still in flight starts the second one.
        logic.actions.appendOlderEntries([], false)
        await expectLogic(logic).toFinishAllListeners()

        expect(reportRequests).toBe(1)
        expect(logic.values.reportTitles).toEqual({ [reportId]: 'Export error rate doubled' })
    })

    // A stored null asserts the report is gone and stops the key being asked for again, so a
    // transient failure that stores one pins the row to its shortened UUID for the whole session.
    // Only a 404 is terminal; anything else has to stay unresolved for a later pass to retry.
    it.each([
        [404, true],
        [500, false],
    ])('remembers a missing report title after status %s: %s', async (status, remembered) => {
        const reportId = '01a0918c-5f5f-74c4-b539-c634a8cb990a'
        useMocks({
            get: {
                [SCRATCHPAD_URL]: () => [200, [entry(`judged:${reportId}`, 'note')]],
                '/api/projects/:team_id/signals/reports/:id/': () => [status, {}],
            },
        })

        logic.actions.loadEntries()
        await expectLogic(logic).toFinishAllListeners()

        expect(Object.hasOwn(logic.values.reportTitles, reportId)).toBe(remembered)
        expect(logic.values.unresolvedReportIds).toEqual(remembered ? [] : [reportId])
    })

    // The harness writes every scout row under the canonical project, so a report a scratchpad key
    // names belongs to the parent. The reports endpoint filters by the team the URL carries, so
    // asking as a child environment 404s every title and caches each miss.
    it('asks the canonical project for a report title from a child environment', async () => {
        const reportId = '01a0918c-5f5f-74c4-b539-c634a8cb990a'
        const reportPaths: string[] = []
        useMocks({
            get: {
                [SCRATCHPAD_URL]: () => [200, [entry(`judged:${reportId}`, 'note')]],
                '/api/projects/:team_id/signals/reports/:id/': ({ request }) => {
                    reportPaths.push(new URL(request.url).pathname)
                    return [200, { id: reportId, title: 'Export error rate doubled' }]
                },
            },
        })
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: 4242, project_id: 99 })

        logic.actions.loadEntries()
        await expectLogic(logic).toFinishAllListeners()

        expect(reportPaths).toEqual([`/api/projects/99/signals/reports/${reportId}/`])
    })

    // 1,000 rows is a cap, not a total. The header has to say what span they cover, or a busy
    // project's few hours of memory reads as everything the fleet has ever learned.
    it.each([
        ['nothing loaded', null, null],
        ['a window ending 30 hours back', 30, 'last 30 h'],
        ['a window ending 10 days back', 24 * 10, 'last 10 days'],
    ])('describes the loaded span for %s', (_name, hoursBack, expected) => {
        const entries =
            hoursBack === null
                ? null
                : [
                      { ...entry('pattern:new', 'note'), updated_at: new Date().toISOString() },
                      {
                          ...entry('pattern:old', 'note'),
                          updated_at: new Date(Date.now() - hoursBack * 3600_000).toISOString(),
                      },
                  ]
        expect(describeLoadedSpan(entries)).toEqual(expected)
    })

    it('keeps the card usable when the body lookup fails', async () => {
        useMocks({ get: { [SCRATCHPAD_URL]: () => [500, {}] } })

        logic.actions.toggleEntry(TRUNCATED.key)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.loadingContentKeys).toEqual([])
        expect(logic.values.fullContentByKey).toEqual({})
        expect(logic.values.expandedKeys).toEqual([TRUNCATED.key])
    })
})
