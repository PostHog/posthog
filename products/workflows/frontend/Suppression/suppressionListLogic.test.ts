import { waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as messagingApi from 'products/messaging/frontend/generated/api'
import type {
    MessageSuppressionApi,
    PaginatedMessageSuppressionApi,
} from 'products/messaging/frontend/generated/api.schemas'

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

            expect(logic.values.suppressions).toEqual(freshResult)
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

        // A fake of the suppression API that holds the list, so another session can change it between requests.
        const useSuppressionListServer = (
            listed: string[],
            {
                sources = {},
                pastEnd = 'rejected',
            }: { sources?: Record<string, string>; pastEnd?: 'rejected' | 'empty' } = {}
        ): { rows: string[]; removalBodies: unknown[] } => {
            const server = { rows: listed.map((name) => `${name}@example.com`), removalBodies: [] as unknown[] }
            useMocks({
                get: {
                    '/api/projects/:team/messaging_suppressions/suppressions/': ({ request }) => {
                        const page = Number(new URL(request.url).searchParams.get('page') ?? 1)
                        const results = server.rows.slice((page - 1) * pageSize, page * pageSize)
                        if (page > 1 && results.length === 0 && pastEnd === 'rejected') {
                            return [404, { detail: 'Invalid page.' }]
                        }
                        return [
                            200,
                            {
                                count: server.rows.length,
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

        const confirmRemoval = async (
            logic: ReturnType<typeof suppressionListLogic.build>,
            entries: MessageSuppressionApi[]
        ): Promise<void> => {
            const openDialog = jest.spyOn(LemonDialog, 'open').mockImplementation(() => {})
            logic.actions.confirmRemove(entries)
            openDialog.mock.calls[0][0].primaryButton?.onClick?.({} as any)
            openDialog.mockRestore()
            await settled(logic)
        }

        const shownRows = (logic: ReturnType<typeof suppressionListLogic.build>): string[] =>
            logic.values.suppressions.results.map((row) => row.identifier)

        it.each([
            ['a bounced address', 'BOUNCE', false],
            ['a spam complaint', 'COMPLAINT', true],
        ])('sends the complaint confirmation only for %s', async (_label, source, confirmComplaints) => {
            const server = useSuppressionListServer(['a', 'b'], { sources: { 'a@example.com': source } })
            const logic = suppressionListLogic()
            logic.mount()
            await settled(logic)

            await confirmRemoval(logic, [suppressionRow('a@example.com', source)])

            expect(server.removalBodies).toEqual([
                { identifiers: ['a@example.com'], confirm_complaints: confirmComplaints },
            ])
            expect(shownRows(logic)).toEqual(['b@example.com'])
        })

        it.each([
            [
                'stays on a page that rows from the next page refill',
                ['a', 'b', 'c', 'd', 'e'],
                'c',
                ['c', 'd'],
                'rejected',
                2,
                ['e'],
            ],
            ['goes back from a page the API rejects', ['a', 'b', 'c', 'd'], 'd', ['c'], 'rejected', 1, ['a', 'b']],
            ['goes back from a page the API returns empty', ['a', 'b', 'c', 'd'], 'd', ['c'], 'empty', 1, ['a', 'b']],
        ] as const)(
            '%s after another session removes a row from it',
            async (_label, listed, removedElsewhere, selected, pastEnd, expectedPage, expectedRows) => {
                const server = useSuppressionListServer([...listed], { pastEnd })
                const logic = suppressionListLogic()
                logic.mount()
                await settled(logic)
                logic.actions.loadSuppressions(2)
                await settled(logic)
                server.rows = server.rows.filter((id) => id !== `${removedElsewhere}@example.com`)

                await confirmRemoval(
                    logic,
                    selected.map((name) => suppressionRow(`${name}@example.com`))
                )

                expect(logic.values.currentPage).toBe(expectedPage)
                expect(shownRows(logic)).toEqual(expectedRows.map((name) => `${name}@example.com`))
            }
        )
    })
})
