import { expectLogic } from 'kea-test-utils'

import { LemonDialog } from '@posthog/lemon-ui'

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
    })
})
