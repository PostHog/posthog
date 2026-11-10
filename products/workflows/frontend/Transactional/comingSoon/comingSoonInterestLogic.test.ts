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

interface StoredResponse {
    submissionId: string
    surveyId: string
    completed: boolean
    answers: Record<string, string>
    surface: string
}

// Stands in for PostHog's survey results: one response per submission id, read from its latest event.
function surveyReceiver(): { responses: () => StoredResponse[] } {
    const stored = new Map<string, StoredResponse>()
    jest.mocked(posthog.capture).mockImplementation((event, properties) => {
        if (event === 'survey sent' && properties) {
            const answers = Object.fromEntries(
                Object.entries(properties)
                    .filter(([key]) => key.startsWith('$survey_response_') && !/^\$survey_response(_\d+)?$/.test(key))
                    .map(([key, value]) => [key.replace('$survey_response_', ''), value])
            )
            stored.set(properties.$survey_submission_id, {
                submissionId: properties.$survey_submission_id,
                surveyId: properties.$survey_id,
                completed: properties.$survey_completed,
                answers,
                surface: properties.feedback_surface,
            })
        }
        return undefined
    })
    return { responses: () => [...stored.values()] }
}

const interestOnly = (submissionId: unknown = expect.any(String)): StoredResponse => ({
    submissionId: submissionId as string,
    surveyId: 'survey-1',
    completed: false,
    answers: { 'interest-q': 'Interested' },
    surface: 'test',
})

describe('comingSoonInterestLogic', () => {
    let logic: ReturnType<typeof comingSoonInterestLogic.build>
    let receiver: ReturnType<typeof surveyReceiver>

    const mountFor = (accountId: string): void => {
        logic.unmount()
        initKeaTests()
        logic = comingSoonInterestLogic({ ...SURVEY, accountId })
        logic.mount()
    }

    beforeEach(() => {
        localStorage.clear()
        initKeaTests()
        jest.clearAllMocks()
        jest.useFakeTimers()
        receiver = surveyReceiver()
        logic = comingSoonInterestLogic(SURVEY)
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.useRealTimers()
    })

    it('records interest once and reopens the note on a second click', () => {
        logic.actions.registerInterest()
        jest.advanceTimersByTime(1000)
        logic.actions.closeNote()
        expect(logic.values.noteOpen).toBe(false)
        logic.actions.registerInterest()

        expect(receiver.responses()).toEqual([interestOnly()])
        expect(logic.values.noteOpen).toBe(true)
    })

    it('keeps the note open when the second click of a double click lands on the overlay', () => {
        logic.actions.registerInterest()
        jest.advanceTimersByTime(200)
        logic.actions.closeNote()

        expect(logic.values.noteOpen).toBe(true)
    })

    it('keeps the note and the interest on one submission after a reload', () => {
        // A fresh kea context reads the persisted id as a page load does, so a person who comes back
        // cannot split their answers into two responses or be counted twice.
        logic.actions.registerInterest()
        mountFor('')

        logic.actions.registerInterest()
        logic.actions.setNote('  Our billing system only speaks SMTP  ')
        logic.actions.submitNote()
        expect(logic.values.noteOpen).toBe(false)
        // The note event already carries the interest, so a later click must not replace it with one that has no note.
        logic.actions.registerInterest()

        expect(receiver.responses()).toEqual([
            {
                ...interestOnly(),
                completed: true,
                answers: { 'interest-q': 'Interested', 'note-q': 'Our billing system only speaks SMTP' },
            },
        ])
    })

    it('uses one submission per person, so a stale tab or a second browser adds no row', () => {
        mountFor('first-account')
        logic.actions.registerInterest()
        localStorage.clear()
        mountFor('first-account')

        logic.actions.registerInterest()

        expect(receiver.responses()).toEqual([interestOnly('first-account')])
    })

    it("hides the last account's interest and note from the next account on the same browser", () => {
        mountFor('first-account')
        logic.actions.registerInterest()
        logic.actions.setNote('Private draft')

        mountFor('second-account')

        expect(logic.values.note).toBe('')
        expect(logic.values.hasRecordedInterest).toBe(false)
        logic.actions.registerInterest()
        expect(receiver.responses()).toEqual([interestOnly('first-account'), interestOnly('second-account')])
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

        expect(receiver.responses()).toEqual([interestOnly()])
        expect(logic.values.noteOpen).toBe(true)
    })
})
