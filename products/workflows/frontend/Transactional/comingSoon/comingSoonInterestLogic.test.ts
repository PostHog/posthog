import posthog from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { comingSoonInterestLogic } from './comingSoonInterestLogic'

jest.mock('posthog-js')

const SURVEY = {
    surveyId: 'survey-1',
    interestQuestionId: 'interest-q',
    noteQuestionId: 'note-q',
    surface: 'test',
    accountId: '',
}

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

    it('resends the interest under the same submission and reopens the note on a second click', () => {
        jest.useFakeTimers()
        logic.actions.registerInterest()
        jest.advanceTimersByTime(1000)
        logic.actions.closeNote()
        expect(logic.values.noteOpen).toBe(false)
        logic.actions.registerInterest()

        expect(surveySent()).toHaveLength(2)
        expect(surveySent()[1].$survey_submission_id).toBe(surveySent()[0].$survey_submission_id)
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
        expect(logic.values.noteOpen).toBe(false)
        // The note event already carries the interest, so a later click must not replace it with one that has no note.
        logic.actions.registerInterest()

        expect(surveySent()).toHaveLength(3)
        expect(surveySent()[2]).toMatchObject({
            $survey_submission_id: submissionId,
            $survey_completed: true,
            '$survey_response_interest-q': 'Interested',
            '$survey_response_note-q': 'Our billing system only speaks SMTP',
        })
    })

    it("uses one submission per person and hides the last account's answers from the next account", () => {
        logic.unmount()
        logic = comingSoonInterestLogic({ ...SURVEY, accountId: 'first-account' })
        logic.mount()
        logic.actions.registerInterest()
        logic.actions.setNote('Private draft')
        logic.unmount()
        initKeaTests()

        logic = comingSoonInterestLogic({ ...SURVEY, accountId: 'second-account' })
        logic.mount()

        expect(surveySent()[0].$survey_submission_id).toBe('first-account')
        expect(logic.values.note).toBe('')
        expect(logic.values.hasRecordedInterest).toBe(false)
        logic.actions.registerInterest()
        expect(surveySent()[1].$survey_submission_id).toBe('second-account')
    })

    it.each([
        ['the same account', 'first-account', 'Saved draft', true],
        ['another account', 'second-account', '', false],
    ])('restores answers saved before storage was split by account only for %s', (_, accountId, note, restored) => {
        const legacyKey = (reducer: string): string =>
            `products.workflows.frontend.Transactional.comingSoon.comingSoonInterestLogic.${SURVEY.surveyId}.${reducer}`
        localStorage.setItem(legacyKey('submissionId'), JSON.stringify('first-account'))
        localStorage.setItem(legacyKey('note'), JSON.stringify('Saved draft'))
        logic.unmount()
        initKeaTests()

        logic = comingSoonInterestLogic({ ...SURVEY, accountId })
        logic.mount()

        expect(logic.values.note).toBe(note)
        expect(logic.values.hasRecordedInterest).toBe(restored)
        expect(localStorage.getItem(legacyKey('note')) === null).toBe(restored)
    })

    it('does not send a blank note', () => {
        logic.actions.registerInterest()
        logic.actions.setNote('   ')
        logic.actions.submitNote()

        expect(surveySent()).toHaveLength(1)
        expect(logic.values.noteOpen).toBe(true)
    })
})
