import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import api from 'lib/api'

import { initKeaTests } from '~/test/init'

import {
    signalsScoutRunsList,
    signalsScoutRunsRecentEmissions,
    signalsScoutRunsRecentPerScout,
} from 'products/signals/frontend/generated/api'

import { SignalReport, SignalScoutRunSummary } from '../types'
import { SCOUT_RUNS_PER_SCOUT } from '../utils/scoutRunsWindow'
import { scoutDetailLogic } from './scoutDetailLogic'
import { scoutFleetLogic } from './scoutFleetLogic'

jest.mock('posthog-js')
jest.mock('products/signals/frontend/generated/api', () => ({
    signalsScoutRunsEmissionReports: jest.fn().mockResolvedValue([]),
    signalsScoutRunsEmissions: jest.fn().mockResolvedValue([]),
    signalsScoutRunsFindingsSummary: jest.fn(),
    signalsScoutRunsList: jest.fn(),
    signalsScoutRunsRecentEmissions: jest.fn(),
    signalsScoutRunsRecentPerScout: jest.fn(),
    signalsScoutConfigList: jest.fn().mockResolvedValue([]),
    signalsScoutConfigSync: jest.fn().mockResolvedValue([]),
}))

const mockRunsList = signalsScoutRunsList as jest.MockedFunction<typeof signalsScoutRunsList>
const mockRecentPerScout = signalsScoutRunsRecentPerScout as jest.MockedFunction<typeof signalsScoutRunsRecentPerScout>
const mockRecentEmissions = signalsScoutRunsRecentEmissions as jest.MockedFunction<
    typeof signalsScoutRunsRecentEmissions
>

const SKILL = 'signals-scout-errors'

function makeRun(
    runId: string,
    hoursAgo: number,
    overrides: Partial<SignalScoutRunSummary> = {}
): SignalScoutRunSummary {
    const createdAt = new Date(Date.UTC(2026, 10, 28, 12) - hoursAgo * 3_600_000).toISOString()
    return {
        run_id: runId,
        total_spend: null,
        skill_name: SKILL,
        skill_version: 1,
        status: 'completed',
        metadata: {},
        created_at: createdAt,
        started_at: createdAt,
        completed_at: createdAt,
        summary: '',
        summary_lead: '',
        emitted_count: 0,
        emitted_finding_ids: [],
        emitted_report_ids: [],
        edited_report_ids: [],
        ...overrides,
    }
}

/** `count` runs one hour apart, the first `startHoursAgo` hours old, newest first. */
function makeRuns(prefix: string, count: number, startHoursAgo: number): SignalScoutRunSummary[] {
    return Array.from({ length: count }, (_, index) =>
        makeRun(`${prefix}-${String(index).padStart(2, '0')}`, startHoursAgo + index)
    )
}

describe('scoutDetailLogic', () => {
    let logic: ReturnType<typeof scoutDetailLogic.build>
    const windowRuns = makeRuns('window', SCOUT_RUNS_PER_SCOUT, 1)
    const oldestWindowRun = windowRuns[windowRuns.length - 1]

    async function mountWith(window: SignalScoutRunSummary[]): Promise<void> {
        mockRecentPerScout.mockResolvedValue(window)
        logic = scoutDetailLogic({ skillName: SKILL })
        logic.mount()
        await expectLogic(logic).toDispatchActions([scoutFleetLogic.actionTypes.loadScoutRunsForSkillSuccess])
        await expectLogic(logic).toFinishAllListeners()
    }

    beforeEach(() => {
        initKeaTests()
        mockRunsList.mockReset()
        mockRecentPerScout.mockReset()
        mockRecentEmissions.mockReset().mockResolvedValue([])
        jest.mocked(posthog.capture).mockClear()
    })

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    it('pages older runs from the oldest loaded run and stops at a short page', async () => {
        await mountWith(windowRuns)
        const firstPage = makeRuns('older', SCOUT_RUNS_PER_SCOUT, SCOUT_RUNS_PER_SCOUT + 5)
        const lastPage = makeRuns('oldest', 3, 2 * SCOUT_RUNS_PER_SCOUT + 10)
        mockRunsList.mockResolvedValueOnce(firstPage).mockResolvedValueOnce(lastPage)

        await expectLogic(logic, () => logic.actions.loadOlder('runs')).toDispatchActions(['loadOlderRunsSuccess'])
        expect(mockRunsList).toHaveBeenLastCalledWith(expect.any(String), {
            skill_name: SKILL,
            limit: SCOUT_RUNS_PER_SCOUT,
            date_to: oldestWindowRun.created_at,
            before_id: oldestWindowRun.run_id,
        })
        expect(logic.values.olderHistoryMayExist.runs).toBe(true)

        await expectLogic(logic, () => logic.actions.loadOlder('runs')).toDispatchActions(['loadOlderRunsSuccess'])
        expect(mockRunsList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({
                date_to: firstPage[firstPage.length - 1].created_at,
                before_id: firstPage[firstPage.length - 1].run_id,
            })
        )

        const history = logic.values.historyRuns.map((run) => run.run_id)
        expect(history).toHaveLength(2 * SCOUT_RUNS_PER_SCOUT + 3)
        expect(history[0]).toBe('window-00')
        expect(history[history.length - 1]).toBe('oldest-02')
        expect(logic.values.olderRuns.exhausted).toBe(true)
        expect(logic.values.olderHistoryMayExist.runs).toBe(false)
        expect(jest.mocked(posthog.capture).mock.lastCall?.[1]).toMatchObject({
            action_type: 'load_older',
            tab: 'runs',
            page: 2,
            filter: 'all',
        })
    })

    it('asks older pages for the open filter pill, and drops them when the pill changes', async () => {
        await mountWith(windowRuns)
        mockRunsList.mockResolvedValue([makeRun('failed-older', 40, { status: 'failed' })])

        logic.actions.setRunFilter('failed')
        await expectLogic(logic, () => logic.actions.loadOlder('runs')).toDispatchActions(['loadOlderRunsSuccess'])
        expect(mockRunsList).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ status: 'failed' }))
        expect(logic.values.historyRuns.map((run) => run.run_id)).toContain('failed-older')

        logic.actions.setRunFilter('all')
        expect(logic.values.olderRuns.runs).toEqual([])
        expect(logic.values.historyRuns).toHaveLength(SCOUT_RUNS_PER_SCOUT)
    })

    it('keeps a run the poll moves out of the window once older pages are open', async () => {
        await mountWith(windowRuns)
        mockRunsList.mockResolvedValue(makeRuns('older', SCOUT_RUNS_PER_SCOUT, SCOUT_RUNS_PER_SCOUT + 5))
        await expectLogic(logic, () => logic.actions.loadOlder('runs')).toDispatchActions(['loadOlderRunsSuccess'])

        mockRecentPerScout.mockResolvedValue([makeRun('newest', 0), ...windowRuns.slice(0, SCOUT_RUNS_PER_SCOUT - 1)])
        await expectLogic(logic, () => scoutFleetLogic.actions.loadScoutRunsForSkill(SKILL)).toDispatchActions([
            scoutFleetLogic.actionTypes.loadScoutRunsForSkillSuccess,
        ])

        const history = logic.values.historyRuns.map((run) => run.run_id)
        expect(history).toContain(oldestWindowRun.run_id)
        expect(history).toHaveLength(SCOUT_RUNS_PER_SCOUT + 1)
    })

    it('adds older reports once each, and reads an older authoring over a newer edit', async () => {
        const getReport = jest
            .spyOn(api.signalReports, 'get')
            .mockImplementation(async (id: string) => ({ id, updated_at: '2026-11-01T00:00:00Z' }) as SignalReport)
        await mountWith([makeRun('window-edit', 1, { edited_report_ids: ['r-1'] })])
        mockRunsList.mockResolvedValue([
            makeRun('older-edit', 30, { edited_report_ids: ['r-2', 'r-1'] }),
            makeRun('older-author', 31, { emitted_report_ids: ['r-1'] }),
        ])

        await expectLogic(logic, () => logic.actions.loadOlder('reports')).toDispatchActions([
            'loadOlderReportsSuccess',
        ])

        expect(mockRunsList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ touched_report: true })
        )
        expect(getReport.mock.calls.map(([id]) => id)).toEqual(['r-1', 'r-2'])
        expect(logic.values.touchedReportCount).toBe(2)
        expect(logic.values.reportRows.map(({ report, action }) => [report.id, action])).toEqual([
            ['r-1', 'authored'],
            ['r-2', 'edited'],
        ])
        expect(logic.values.olderReports.exhausted).toBe(true)
    })

    it.each([
        [[{ id: 'emission-1' }], true],
        [[], false],
    ])('checks whether the scout ever emitted a signal', async (emissions, expected) => {
        mockRecentEmissions.mockResolvedValue(emissions as any)
        await mountWith([])

        expect(mockRecentEmissions).toHaveBeenCalledWith(expect.any(String), { skill_name: SKILL, limit: 1 })
        expect(logic.values.scoutHasSignals).toBe(expected)
    })
})
