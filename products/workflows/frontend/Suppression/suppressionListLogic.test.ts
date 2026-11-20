import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as messagingApi from 'products/messaging/frontend/generated/api'

import { removalWarning, suppressionListLogic } from './suppressionListLogic'

const suppressionRow = (identifier: string, source = 'MANUAL'): any => ({
    id: identifier,
    identifier,
    source,
    reason: '',
    transient_bounce_count: 0,
    last_bounce_at: null,
    last_bounce_diagnostic: null,
    suppressed: true,
    suppressed_at: null,
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
})

describe('suppressionListLogic', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        jest.restoreAllMocks()
    })

    describe('page-state failure isolation', () => {
        // Guards against the "silent-swallow catch returns previous rows -> kea-loaders treats it as
        // success -> currentPage still increments" bug. On a failed page fetch the counter must
        // stay put; otherwise the UI shows the wrong page number over old data, then permanently
        // skips the page it thought it advanced to.
        it('does not advance currentPage when loadNextPage fails', async () => {
            jest.spyOn(messagingApi, 'messagingSuppressionsSuppressionsRetrieve').mockRejectedValue(new Error('boom'))
            const logic = suppressionListLogic()
            logic.mount()
            // Let the mount-time load fail first, so the assertion below can only match the
            // pagination fetch's own failure.
            await expectLogic(logic).toFinishAllListeners()

            await expectLogic(logic, () => {
                logic.actions.loadNextPage()
            }).toDispatchActions(['loadSuppressionsFailure'])

            expect(logic.values.currentPage).toBe(1)
        })

        it('does not roll back currentPage when loadPreviousPage fails', async () => {
            jest.spyOn(messagingApi, 'messagingSuppressionsSuppressionsRetrieve').mockRejectedValue(new Error('boom'))
            const logic = suppressionListLogic()
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setCurrentPage(3)

            await expectLogic(logic, () => {
                logic.actions.loadPreviousPage()
            }).toDispatchActions(['loadSuppressionsFailure'])

            expect(logic.values.currentPage).toBe(3)
        })
    })

    describe('overlapping request isolation', () => {
        it('shows the search results when the next page they replaced arrives late', async () => {
            const listed = ['a@example.com', 'b@example.com', 'c@example.com']
            let releaseNextPage: () => void = () => {}
            const nextPageHeld = new Promise<void>((resolve) => {
                releaseNextPage = resolve
            })
            let nextPageReceived: () => void = () => {}
            const nextPageRequested = new Promise<void>((resolve) => {
                nextPageReceived = resolve
            })
            useMocks({
                get: {
                    '/api/projects/:team/messaging_suppressions/suppressions/': async ({ request }) => {
                        const params = new URL(request.url).searchParams
                        const page = Number(params.get('page') ?? 1)
                        if (page === 2) {
                            nextPageReceived()
                            await nextPageHeld
                        }
                        const matching = listed.filter((id) => id.includes(params.get('search') ?? ''))
                        return [
                            200,
                            {
                                count: matching.length,
                                next:
                                    page * 2 < matching.length ? `${request.url.split('?')[0]}?page=${page + 1}` : null,
                                previous: null,
                                results: matching.slice((page - 1) * 2, page * 2).map((id) => suppressionRow(id)),
                            },
                        ]
                    },
                },
            })
            const logic = suppressionListLogic()
            logic.mount()
            await waitFor(() => expect(logic.values.suppressions.next).not.toBeNull())

            logic.actions.loadNextPage()
            await nextPageRequested
            logic.actions.setSearchTerm('b')
            await waitFor(() => expect(logic.values.suppressions.count).toBe(1))
            releaseNextPage()
            await expectLogic(logic).toFinishAllListeners()

            expect([
                logic.values.currentPage,
                logic.values.suppressions.count,
                logic.values.suppressions.results.map((row) => row.identifier),
            ]).toEqual([1, 1, ['b@example.com']])
        })
    })
    describe('removal warning', () => {
        it.each([
            ['a bounced address', [suppressionRow('a@example.com', 'BOUNCE')], 'Remove', false],
            ['a spam complaint', [suppressionRow('a@example.com', 'COMPLAINT')], 'Remove anyway', true],
            [
                'a selection with one spam complaint',
                [suppressionRow('a@example.com', 'MANUAL'), suppressionRow('b@example.com', 'COMPLAINT')],
                'Remove anyway',
                true,
            ],
        ])('warns about %s', (_label, entries, confirmLabel, mentionsSpam) => {
            const warning = removalWarning(entries)

            expect(warning.confirmLabel).toBe(confirmLabel)
            expect(warning.description.includes('as spam')).toBe(mentionsSpam)
            expect(warning.description).toContain('back on the list')
        })
    })
    describe('confirmed removal', () => {
        it.each([
            ['a bounced address', 'BOUNCE', false],
            ['a spam complaint', 'COMPLAINT', true],
        ])('sends the complaint confirmation only for %s', async (_label, source, confirmComplaints) => {
            jest.spyOn(messagingApi, 'messagingSuppressionsSuppressionsRetrieve').mockResolvedValue({
                count: 0,
                next: null,
                previous: null,
                results: [],
            })
            const remove = jest
                .spyOn(messagingApi, 'messagingSuppressionsBulkRemoveSuppressionsCreate')
                .mockResolvedValue({ removed: ['a@example.com'], not_found: [] })
            const openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
            const logic = suppressionListLogic()
            logic.mount()

            logic.actions.confirmRemove([suppressionRow('a@example.com', source)])
            openDialog.mock.calls[0][0].primaryButton?.onClick?.({} as any)
            await expectLogic(logic).toDispatchActions(['removeSuppressionsSuccess'])

            expect(remove).toHaveBeenCalledWith(expect.any(String), {
                identifiers: ['a@example.com'],
                confirm_complaints: confirmComplaints,
            })
        })

        it.each([
            [
                'steps back when another session already removed part of a selection that filled the last page',
                { listed: 'abcd', startPage: 2, removedElsewhere: 'c', selected: 'cd', expected: [1, 'ab'] },
            ],
            [
                'stays on a page that later rows move up into',
                { listed: 'abcde', startPage: 2, removedElsewhere: '', selected: 'cd', expected: [2, 'e'] },
            ],
            [
                'steps back when the removal empties the last page the user moved to while it ran',
                { listed: 'abcde', startPage: 3, removedElsewhere: '', selected: 'c', expected: [2, 'de'] },
            ],
        ])('%s', async (_label, { listed: initial, startPage, removedElsewhere, selected, expected }) => {
            const addresses = (names: string): string[] => [...names].map((name) => `${name}@example.com`)
            let listed = addresses(initial)
            useMocks({
                get: {
                    '/api/projects/:team/messaging_suppressions/suppressions/': ({ request }) => {
                        const page = Number(new URL(request.url).searchParams.get('page') ?? 1)
                        const rows = listed.slice((page - 1) * 2, page * 2)
                        if (page > 1 && rows.length === 0) {
                            return [404, { detail: 'Invalid page.' }]
                        }
                        const next = page * 2 < listed.length ? `${request.url.split('?')[0]}?page=${page + 1}` : null
                        return [
                            200,
                            {
                                count: listed.length,
                                next,
                                previous: null,
                                results: rows.map((id) => suppressionRow(id)),
                            },
                        ]
                    },
                },
                post: {
                    '/api/projects/:team/messaging_suppressions/bulk_remove_suppressions/': async ({ request }) => {
                        const { identifiers } = (await request.json()) as { identifiers: string[] }
                        const removed = identifiers.filter((id) => listed.includes(id))
                        listed = listed.filter((id) => !identifiers.includes(id))
                        return [200, { removed, not_found: identifiers.filter((id) => !removed.includes(id)) }]
                    },
                },
            })
            const logic = suppressionListLogic()
            logic.mount()
            await waitFor(() => expect(logic.values.suppressions.next).not.toBeNull())
            logic.actions.loadSuppressions(startPage)
            await waitFor(() => expect(logic.values.currentPage).toBe(startPage))
            listed = listed.filter((id) => !addresses(removedElsewhere).includes(id))

            logic.actions.removeSuppressions({ identifiers: addresses(selected), confirmComplaints: false })

            const [expectedPage, expectedRows] = expected as [number, string]
            await waitFor(() =>
                expect([
                    logic.values.currentPage,
                    logic.values.suppressions.results.map((row) => row.identifier),
                ]).toEqual([expectedPage, addresses(expectedRows)])
            )
        })
    })
})
