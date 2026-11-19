import { fireEvent, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as messagingApi from 'products/messaging/frontend/generated/api'
import type { PaginatedMessageSuppressionApi } from 'products/messaging/frontend/generated/api.schemas'

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
        // Guards the loader breakpoint: a pagination fetch that resolves after a newer reload
        // (e.g. a debounced search) must be discarded, not overwrite the newer rows and desync
        // currentPage from what the table shows.
        it('discards a stale pagination response that resolves after a newer reload', async () => {
            let resolveStalePage: (value: PaginatedMessageSuppressionApi) => void = () => {}
            const stalePagePromise = new Promise<PaginatedMessageSuppressionApi>((resolve) => {
                resolveStalePage = resolve
            })
            const initialResult: PaginatedMessageSuppressionApi = {
                count: 1,
                next: null,
                previous: null,
                results: [suppressionRow('initial@example.com')],
            }
            const freshResult: PaginatedMessageSuppressionApi = {
                count: 1,
                next: null,
                previous: null,
                results: [suppressionRow('fresh@example.com')],
            }
            jest.spyOn(messagingApi, 'messagingSuppressionsSuppressionsRetrieve')
                .mockResolvedValueOnce(initialResult)
                .mockImplementationOnce(() => stalePagePromise)
                .mockResolvedValueOnce(freshResult)

            const logic = suppressionListLogic()
            logic.mount()
            // Let the mount-time load settle so the mocks line up with the two racing requests.
            await expectLogic(logic).toDispatchActions(['loadSuppressionsSuccess'])

            logic.actions.loadNextPage()
            await expectLogic(logic, () => {
                logic.actions.loadSuppressions()
            }).toDispatchActions(['loadSuppressionsSuccess'])

            resolveStalePage({
                count: 100,
                next: 'next-url',
                previous: null,
                results: [suppressionRow('stale@example.com')],
            })
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.suppressions).toEqual({ ...freshResult, page: 1 })
            expect(logic.values.currentPage).toBe(1)
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
        const pageSize = 2
        const address = (name: string): string => `${name}@example.com`

        type ListServer = {
            rows: string[]
            removalBodies: unknown[]
            requests: URLSearchParams[]
        }

        // A fake of the suppression API that holds the list, so another session can change it between requests.
        const useSuppressionListServer = (
            listed: string[],
            {
                sources = {},
                pastEnd = 'rejected',
                afterPage,
                holdRemoval,
                holdPage,
            }: {
                sources?: Record<string, string>
                pastEnd?: 'rejected' | 'empty'
                afterPage?: (page: number, server: ListServer) => void
                holdRemoval?: Promise<void>
                holdPage?: (params: URLSearchParams) => Promise<void> | undefined
            } = {}
        ): ListServer => {
            const server: ListServer = { rows: listed.map(address), removalBodies: [], requests: [] }
            useMocks({
                get: {
                    '/api/projects/:team/messaging_suppressions/suppressions/': async ({ request }) => {
                        const params = new URL(request.url).searchParams
                        server.requests.push(params)
                        await holdPage?.(params)
                        const page = Number(params.get('page') ?? 1)
                        const matching = server.rows.filter((id) => id.includes(params.get('search') ?? ''))
                        const results = matching.slice((page - 1) * pageSize, page * pageSize)
                        afterPage?.(page, server)
                        if (page > 1 && results.length === 0 && pastEnd === 'rejected') {
                            return [404, { detail: 'Invalid page.' }]
                        }
                        return [
                            200,
                            {
                                count: matching.length,
                                next: null,
                                previous: null,
                                results: results.map((id) => suppressionRow(id, sources[id])),
                            },
                        ]
                    },
                },
                post: {
                    '/api/projects/:team/messaging_suppressions/bulk_remove_suppressions/': async ({ request }) => {
                        const body = (await request.json()) as { identifiers: string[] }
                        await holdRemoval
                        server.removalBodies.push(body)
                        const removed = body.identifiers.filter((id) => server.rows.includes(id))
                        server.rows = server.rows.filter((id) => !body.identifiers.includes(id))
                        return [200, { removed, not_found: body.identifiers.filter((id) => !removed.includes(id)) }]
                    },
                },
            })
            return server
        }

        const settled = async (logic: ReturnType<typeof suppressionListLogic.build>): Promise<void> => {
            await waitFor(() =>
                expect([logic.values.suppressionsLoading, logic.values.removedSuppressionsLoading]).toEqual([
                    false,
                    false,
                ])
            )
        }

        const openOnPage = async (page: number): Promise<ReturnType<typeof suppressionListLogic.build>> => {
            const logic = suppressionListLogic()
            logic.mount()
            await settled(logic)
            logic.actions.loadSuppressions(page)
            await settled(logic)
            return logic
        }

        const shown = (logic: ReturnType<typeof suppressionListLogic.build>): [number, string[]] => [
            logic.values.currentPage,
            logic.values.suppressions.results.map((row) => row.identifier),
        ]

        it.each([
            ['a bounced address', 'BOUNCE', 'Remove', false],
            ['a spam complaint', 'COMPLAINT', 'Remove anyway', true],
        ])(
            'sends the complaint confirmation only for %s, once the user confirms the dialog',
            async (_label, source, confirmLabel, confirmComplaints) => {
                const server = useSuppressionListServer(['a', 'b'], { sources: { [address('a')]: source } })
                const logic = await openOnPage(1)

                logic.actions.confirmRemove([logic.values.suppressions.results[0]])
                fireEvent.click(await screen.findByText(confirmLabel))
                await waitFor(() => expect(server.removalBodies).toHaveLength(1))
                await settled(logic)

                expect(server.removalBodies).toEqual([
                    { identifiers: [address('a')], confirm_complaints: confirmComplaints },
                ])
                expect(shown(logic)).toEqual([1, [address('b')]])
            }
        )

        it.each([
            // Rows from the next page move up, so the page is still there.
            [
                'stays on a page that the next page refills',
                ['a', 'b', 'c', 'd', 'e'],
                2,
                ['c'],
                ['c', 'd'],
                'rejected',
                [2, ['e']],
            ],
            [
                'goes back from a page the API rejects',
                ['a', 'b', 'c', 'd'],
                2,
                ['d'],
                ['c'],
                'rejected',
                [1, ['a', 'b']],
            ],
            [
                'goes back from a page the API returns empty',
                ['a', 'b', 'c', 'd'],
                2,
                ['d'],
                ['c'],
                'empty',
                [1, ['a', 'b']],
            ],
            // The list loses two pages, so the page before this one is gone too.
            [
                'goes back to the last page when the list loses two pages',
                ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'],
                4,
                ['a', 'b', 'c', 'd'],
                ['h'],
                'rejected',
                [2, ['g']],
            ],
        ] as const)(
            '%s after another session removes rows from the list',
            async (_label, listed, openPage, removedElsewhere, selected, pastEnd, expected) => {
                const server = useSuppressionListServer([...listed], { pastEnd })
                const logic = await openOnPage(openPage)
                server.rows = server.rows.filter((id) => !removedElsewhere.map(address).includes(id))

                logic.actions.removeSuppressions({ identifiers: selected.map(address), confirmComplaints: false })
                await settled(logic)

                expect(shown(logic)).toEqual([expected[0], expected[1].map(address)])
            }
        )

        it('shows page 1 when the last page goes away while the load falls back to it', async () => {
            let fellBack = false
            const server = useSuppressionListServer(['a', 'b', 'c', 'd', 'e'], {
                afterPage: (page, list) => {
                    if (fellBack && page === 1) {
                        list.rows = list.rows.filter((id) => ![address('c'), address('d')].includes(id))
                    }
                },
            })
            const logic = await openOnPage(3)
            fellBack = true

            logic.actions.removeSuppressions({ identifiers: [address('e')], confirmComplaints: false })
            await settled(logic)

            expect(server.rows).toEqual([address('a'), address('b')])
            expect(shown(logic)).toEqual([1, [address('a'), address('b')]])
        })

        it('shows the first page of a search that loads while a removal is pending', async () => {
            let releaseRemoval: () => void = () => {}
            let releaseSearch: () => void = () => {}
            const searchHeld = new Promise<void>((resolve) => {
                releaseSearch = resolve
            })
            let searches = 0
            const server = useSuppressionListServer(['a', 'b', 'c', 'd', 'bb', 'bc', 'bd'], {
                holdRemoval: new Promise<void>((resolve) => {
                    releaseRemoval = resolve
                }),
                holdPage: (params) => (params.get('search') === 'b' && searches++ === 0 ? searchHeld : undefined),
            })
            const logic = await openOnPage(2)

            logic.actions.removeSuppressions({ identifiers: [address('c')], confirmComplaints: false })
            logic.actions.setSearchTerm('b')
            await waitFor(() => expect(searches).toBe(1))
            releaseRemoval()
            await waitFor(() => expect(server.removalBodies).toHaveLength(1))
            releaseSearch()
            await settled(logic)

            expect(shown(logic)).toEqual([1, [address('b'), address('bb')]])
        })
    })
})
