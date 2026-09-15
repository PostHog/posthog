import { expectLogic } from 'kea-test-utils'
import { Survey, SurveyQuestionType } from 'posthog-js'

import { initKeaTests } from '~/test/init'

import { exampleApiSurvey, exampleSurveyClient } from './apiSurvey.fixtures'
import { apiSurveyLogic } from './apiSurveyLogic'

describe('apiSurveyLogic', () => {
    beforeEach(() => {
        initKeaTests()
        crypto.randomUUID = () => '00000000-0000-4000-8000-000000000001'
    })

    it('snapshots questions and context and sends one response using question IDs', async () => {
        const survey = {
            ...structuredClone(exampleApiSurvey),
            current_iteration: 3,
            current_iteration_start_date: '2026-01-01T00:00:00Z',
        }
        const context = { feedback_surface: 'example', nested: { version: 1 }, $survey_id: 'cannot-override' }
        const client = exampleSurveyClient([survey])
        const capture = jest.spyOn(client, 'capture')
        const logic = apiSurveyLogic({ surveyId: survey.id, instanceId: 'one', client, context, includeReplay: true })
        const unmount = logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        survey.questions[0].question = 'Changed after display'
        context.nested.version = 2
        logic.actions.setAnswer('goal', 'I wanted to find the settings and got lost.')
        logic.actions.setAnswer('outcome', 'Not an option')
        expect(logic.values.canSubmit).toBe(false)
        logic.actions.setAnswer('outcome', 'No')
        expect(logic.values.canSubmit).toBe(true)
        logic.actions.submit()
        logic.actions.submit()
        const responses = capture.mock.calls.filter(([event]) => event === 'survey sent')
        expect(responses).toHaveLength(1)
        expect(responses[0][1]).toMatchObject({
            $survey_id: survey.id,
            $survey_iteration: 3,
            $survey_iteration_start_date: '2026-01-01T00:00:00Z',
            $survey_response_goal: 'I wanted to find the settings and got lost.',
            $survey_response_outcome: 'No',
            $survey_completed: true,
            nested: { version: 1 },
            sessionRecordingUrl: 'https://example.com/replay',
            $survey_questions: exampleApiSurvey.questions.map(({ id, question }) => ({ id, question })),
        })
        expect(logic.values.completed).toBe(true)
        unmount()
    })

    it('preserves answers and the submission ID when capture fails', async () => {
        const client = exampleSurveyClient()
        const capture = jest.spyOn(client, 'capture')
        const logic = apiSurveyLogic({
            surveyId: exampleApiSurvey.id,
            instanceId: 'retry',
            client,
            context: { sessionRecordingUrl: 'https://example.com/unwanted-replay' },
        })
        const unmount = logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.setAnswer('goal', 'A concrete goal')
        logic.actions.setAnswer('outcome', 'Yes')
        const submissionId = logic.values.submissionId
        capture.mockReturnValueOnce(undefined)
        logic.actions.submit()
        expect(logic.values.completed).toBe(false)
        expect(logic.values.submitting).toBe(false)
        expect(logic.values.answers.goal).toBe('A concrete goal')
        logic.actions.submit()
        expect(logic.values.completed).toBe(true)
        expect(logic.values.submissionId).toBe(submissionId)
        expect(capture.mock.calls[0][1]).not.toHaveProperty('sessionRecordingUrl')
        unmount()
    })

    it.each(['missing', 'duplicate IDs', 'branching', 'validation', 'link'] as const)(
        'does not show an incompatible or %s survey',
        async (kind) => {
            const survey = structuredClone(exampleApiSurvey)
            if (kind === 'duplicate IDs') {
                survey.questions[1].id = survey.questions[0].id
            }
            if (kind === 'branching') {
                survey.questions[0].branching = { type: 'end' }
            }
            if (kind === 'validation') {
                survey.questions[0].validation = [{ type: 'minLength', value: 10 }] as never
            }
            if (kind === 'link') {
                survey.questions[0] = {
                    id: 'link',
                    type: SurveyQuestionType.Link,
                    question: 'Visit a link',
                    link: 'https://example.com',
                }
            }
            const client = exampleSurveyClient(kind === 'missing' ? [] : [survey])
            const capture = jest.spyOn(client, 'capture')
            const logic = apiSurveyLogic({ surveyId: survey.id, instanceId: kind, client })
            const unmount = logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.survey).toBeNull()
            expect(logic.values.loading).toBe(false)
            expect(capture).not.toHaveBeenCalled()
            unmount()
        }
    )

    it('ignores a survey response after the form unmounts', async () => {
        let respond!: (surveys: Survey[]) => void
        const client = {
            ...exampleSurveyClient(),
            getSurveys: (callback: (surveys: Survey[]) => void) => {
                respond = callback
            },
        }
        const capture = jest.spyOn(client, 'capture')
        const logic = apiSurveyLogic({ surveyId: exampleApiSurvey.id, instanceId: 'late', client })
        const unmount = logic.mount()
        unmount()
        respond([exampleApiSurvey])
        await Promise.resolve()
        expect(capture).not.toHaveBeenCalled()
    })
})
