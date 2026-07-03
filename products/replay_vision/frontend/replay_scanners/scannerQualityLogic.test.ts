import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { visionScannersObservationsList, visionScannersObservationsStatsRetrieve } from '../generated/api'
import { QUALITY_PAGE_SIZE, RatedFilterValue, scannerQualityLogic } from './scannerQualityLogic'

jest.mock('../generated/api', () => ({
    visionScannersObservationsList: jest.fn(),
    visionScannersObservationsStatsRetrieve: jest.fn(),
}))

const TEAM_ID = String(MOCK_DEFAULT_TEAM.id)

describe('scannerQualityLogic', () => {
    let logic: ReturnType<typeof scannerQualityLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        initKeaTests()
        ;(visionScannersObservationsList as jest.Mock).mockResolvedValue({
            results: [
                { id: 'obs-1', session_id: 'sess-1', status: 'succeeded', label: null },
                { id: 'obs-2', session_id: 'sess-2', status: 'succeeded', label: null },
            ],
            count: 2,
        })
        ;(visionScannersObservationsStatsRetrieve as jest.Mock).mockResolvedValue({
            labels: { up_total: 0, down_total: 0, by_day: [] },
        })
        logic = scannerQualityLogic({ scannerId: 'scan-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadObservationsSuccess'])
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each<[RatedFilterValue, Record<string, unknown>]>([
        ['all', { status: 'succeeded', limit: QUALITY_PAGE_SIZE }],
        ['rated', { status: 'succeeded', limit: QUALITY_PAGE_SIZE, labeled: true }],
        ['unrated', { status: 'succeeded', limit: QUALITY_PAGE_SIZE, labeled: false }],
    ])('the "%s" filter requests the matching observation set', async (filter, expectedParams) => {
        logic.actions.setRatedFilter(filter)
        await expectLogic(logic).toFinishAllListeners()

        expect(visionScannersObservationsList).toHaveBeenLastCalledWith(TEAM_ID, 'scan-1', expectedParams)
    })

    it('an inline rating updates the row so a remount does not resurrect a stale label', () => {
        logic.actions.labelChanged('obs-2', { is_correct: false, feedback: 'should be yes' })

        expect(logic.values.observations.find((obs) => obs.id === 'obs-2')?.label).toEqual({
            is_correct: false,
            feedback: 'should be yes',
        })
        expect(logic.values.observations.find((obs) => obs.id === 'obs-1')?.label).toBeNull()
    })
})
