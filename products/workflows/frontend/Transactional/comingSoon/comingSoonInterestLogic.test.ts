import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import posthog from 'posthog-js'

import { userLogic } from 'scenes/userLogic'

import { initKeaTests } from '~/test/init'

import { comingSoonInterestLogic } from './comingSoonInterestLogic'

jest.mock('posthog-js')

const SURVEY = { surveyId: 'survey-1', interestQuestionId: 'interest-q', noteQuestionId: 'note-q', surface: 'test' }

const surveySent = (): Record<string, any>[] =>
    (posthog.capture as jest.Mock).mock.calls.filter(([name]) => name === 'survey sent').map(([, props]) => props)

describe('comingSoonInterestLogic', () => {
    let logic: ReturnType<typeof comingSoonInterestLogic.build>

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.clearAllMocks()
        logic = comingSoonInterestLogic(SURVEY)
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('records interest once and reopens the note on a second click', () => {
        jest.useFakeTimers()
        logic.actions.registerInterest()
        jest.advanceTimersByTime(1000)
        logic.actions.closeNote()
        expect(logic.values.noteOpen).toBe(false)
        logic.actions.registerInterest()

        expect(surveySent()).toHaveLength(1)
        expect(surveySent()[0]).toMatchObject({
            $survey_id: 'survey-1',
            $survey_completed: false,
            '$survey_response_interest-q': 'Interested',
            feedback_surface: 'test',
        })
        expect(logic.values.noteOpen).toBe(true)
    })

    it('keeps the note open when the second click of a double click lands on the overlay', () => {
        logic.actions.registerInterest()
        logic.actions.closeNote()

        expect(logic.values.noteOpen).toBe(true)
    })

    it('keeps the note and the interest on one submission after a reload', () => {
        // A fresh kea context reads the persisted id as a page load does, so a person who comes back
        // cannot split their answers into two responses or be counted twice.
        logic.actions.registerInterest()
        const { $survey_submission_id: submissionId } = surveySent()[0]
        logic.unmount()
        initKeaTests()
        logic = comingSoonInterestLogic(SURVEY)
        logic.mount()

        logic.actions.registerInterest()
        logic.actions.setNote('  Our billing system only speaks SMTP  ')
        logic.actions.submitNote()

        expect(surveySent()).toHaveLength(2)
        expect(surveySent()[1]).toMatchObject({
            $survey_submission_id: submissionId,
            $survey_completed: true,
            '$survey_response_interest-q': 'Interested',
            '$survey_response_note-q': 'Our billing system only speaks SMTP',
        })
        expect(logic.values.noteOpen).toBe(false)
    })

    it('uses one submission per person, so a stale tab or a second browser adds no row', () => {
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)

        logic.actions.registerInterest()

        expect(surveySent()[0].$survey_submission_id).toBe(MOCK_DEFAULT_USER.uuid)
    })

    it("hides the last account's interest and note from the next account on the same browser", () => {
        userLogic.mount()
        userLogic.actions.loadUserSuccess(MOCK_DEFAULT_USER)
        logic.actions.registerInterest()
        logic.actions.setNote('Private draft')
        logic.unmount()
        initKeaTests()
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, uuid: 'another-account' })

        logic = comingSoonInterestLogic(SURVEY)
        logic.mount()

        expect(logic.values.note).toBe('')
        expect(logic.values.hasRecordedInterest).toBe(false)
        logic.actions.registerInterest()
        expect(surveySent()[1].$survey_submission_id).toBe('another-account')
    })

    it('does not send a blank note', () => {
        logic.actions.registerInterest()
        logic.actions.setNote('   ')
        logic.actions.submitNote()

        expect(surveySent()).toHaveLength(1)
        expect(logic.values.noteOpen).toBe(true)
    })
})
