/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper. */
import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { INBOX_SUMMARY_DISMISS_MS, INBOX_SUMMARY_FRESH_MS, inboxSummaryLogic } from './inboxSummaryLogic'

const summary = {
    period_start: '2026-09-13T12:00:00Z',
    period_end: '2026-09-20T12:00:00Z',
    merged_pr_count: 4,
    people_count: 3,
    participation_complete: true,
}

describe('inboxSummaryLogic', () => {
    let logic: ReturnType<typeof inboxSummaryLogic.build>
    let readSummary: jest.Mock
    let now: number

    const mountLogic = (): void => {
        logic.mount()
    }

    beforeEach(() => {
        now = Date.parse(summary.period_end)
        jest.spyOn(Date, 'now').mockImplementation(() => now)
        localStorage.clear()
        readSummary = jest.fn(() => [200, summary])
        useMocks({ get: { '/api/projects/:team_id/signals/inbox-summary/': readSummary } })
        initKeaTests()
        logic = inboxSummaryLogic({ teamId: 2, userId: 10, visible: true })
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    it('loads project counts and only refreshes stale results on return', async () => {
        await expectLogic(logic, mountLogic).toFinishAllListeners().toMatchValues({ summary })
        expect(readSummary).toHaveBeenCalledTimes(1)
        await expectLogic(logic, () => logic.actions.refreshSummary()).toFinishAllListeners()
        expect(readSummary).toHaveBeenCalledTimes(1)
        now += INBOX_SUMMARY_FRESH_MS
        await expectLogic(logic, () => {
            window.dispatchEvent(new Event('focus'))
        }).toFinishAllListeners()
        expect(readSummary).toHaveBeenCalledTimes(2)
    })

    it('does not fetch while a detail view hides the panel', async () => {
        logic = inboxSummaryLogic({ teamId: 2, userId: 10, visible: false })
        await expectLogic(logic, mountLogic).toFinishAllListeners()
        expect(readSummary).not.toHaveBeenCalled()
        await expectLogic(logic, () => {
            inboxSummaryLogic({ teamId: 2, userId: 10, visible: true })
        }).toFinishAllListeners()
        expect(readSummary).toHaveBeenCalledTimes(1)
    })

    it('persists dismissal for seven days and resumes on return', async () => {
        await expectLogic(logic, mountLogic).toFinishAllListeners()
        logic.actions.dismissSummary(now + INBOX_SUMMARY_DISMISS_MS)
        expect(logic.values.dismissed).toBe(true)
        logic.unmount()
        logic = inboxSummaryLogic({ teamId: 2, userId: 10, visible: true })
        await expectLogic(logic, mountLogic).toFinishAllListeners()
        expect(logic.values.dismissed).toBe(true)
        expect(readSummary).toHaveBeenCalledTimes(1)
        now += INBOX_SUMMARY_DISMISS_MS
        await expectLogic(logic, () => logic.actions.refreshSummary()).toFinishAllListeners()
        expect(logic.values.dismissed).toBe(false)
        expect(readSummary).toHaveBeenCalledTimes(2)
    })

    it.each([
        { teamId: 3, userId: 10 },
        { teamId: 2, userId: 20 },
    ])('does not share dismissal with $teamId / $userId', async (identity) => {
        await expectLogic(logic, mountLogic).toFinishAllListeners()
        logic.actions.dismissSummary(now + INBOX_SUMMARY_DISMISS_MS)
        logic.unmount()
        logic = inboxSummaryLogic({ ...identity, visible: true })
        await expectLogic(logic, mountLogic).toFinishAllListeners()
        expect(logic.values.dismissed).toBe(false)
        expect(readSummary).toHaveBeenCalledTimes(2)
    })

    it('keeps unknown participation and supports retry after a failed request', async () => {
        readSummary.mockReturnValue([503, { detail: 'Not available' }])
        await expectLogic(logic, mountLogic).toFinishAllListeners().toMatchValues({ failed: true, summary: null })
        const incomplete = { ...summary, people_count: null, participation_complete: false }
        readSummary.mockReturnValue([200, incomplete])
        await expectLogic(logic, () => logic.actions.refreshSummary(true))
            .toFinishAllListeners()
            .toMatchValues({
                failed: false,
                summary: incomplete,
            })
    })
})
