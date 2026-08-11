/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ScratchpadEntryApi } from 'products/signals/frontend/generated/api.schemas'

import { SCRATCHPAD_PREVIEW_CHARS, scratchpadLogic } from './scratchpadLogic'

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

    it('keeps the card usable when the body lookup fails', async () => {
        useMocks({ get: { [SCRATCHPAD_URL]: () => [500, {}] } })

        logic.actions.toggleEntry(TRUNCATED.key)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.loadingContentKeys).toEqual([])
        expect(logic.values.fullContentByKey).toEqual({})
        expect(logic.values.expandedKeys).toEqual([TRUNCATED.key])
    })
})
