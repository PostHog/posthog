import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { visionObservationsLabelCreate, visionObservationsRetrieve } from '../generated/api'
import { replayObservationLogic } from './replayObservationLogic'
import { replayObservationSceneLogic } from './replayObservationSceneLogic'

jest.mock('../generated/api', () => ({
    visionObservationsRetrieve: jest.fn(),
    visionObservationsLabelCreate: jest.fn(),
    visionObservationsLabelDestroy: jest.fn(),
}))

const TEAM_ID = String(MOCK_DEFAULT_TEAM.id)
const OBSERVATION = {
    id: 'obs-1',
    scanner_id: 'scan-1',
    status: 'succeeded',
    label: { id: 'label-1', is_correct: false, feedback: 'old feedback' },
}

describe('replayObservationLogic feedback autosave', () => {
    let logic: ReturnType<typeof replayObservationLogic.build>

    beforeEach(async () => {
        jest.clearAllMocks()
        initKeaTests()
        replayObservationSceneLogic.mount()
        ;(visionObservationsRetrieve as jest.Mock).mockResolvedValue(OBSERVATION)
        ;(visionObservationsLabelCreate as jest.Mock).mockImplementation((_team, _id, body) =>
            Promise.resolve({ id: 'label-1', ...body })
        )
        logic = replayObservationLogic({ id: 'obs-1' })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadObservationSuccess'])
        jest.useFakeTimers()
    })

    afterEach(() => {
        jest.useRealTimers()
        logic?.unmount()
    })

    it('autosaves edited feedback after the debounce', async () => {
        logic.actions.setFeedbackDraft('scanner missed the refund step')
        await jest.advanceTimersByTimeAsync(900)

        expect(visionObservationsLabelCreate).toHaveBeenCalledTimes(1)
        expect(visionObservationsLabelCreate).toHaveBeenCalledWith(TEAM_ID, 'obs-1', {
            is_correct: false,
            feedback: 'scanner missed the refund step',
        })
    })

    it('a Correct click during the debounce wins over the pending autosave', async () => {
        logic.actions.setFeedbackDraft('scanner missed the refund step')
        logic.actions.setLabel(true, '')
        await jest.advanceTimersByTimeAsync(900)

        expect(visionObservationsLabelCreate).toHaveBeenCalledTimes(1)
        expect(visionObservationsLabelCreate).toHaveBeenCalledWith(TEAM_ID, 'obs-1', {
            is_correct: true,
            feedback: '',
        })
    })
})
