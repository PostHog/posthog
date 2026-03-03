import { resetContext } from 'kea'
import { expectLogic, testUtilsPlugin } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Survey, SurveyEventName, SurveyQuestionType } from '~/types'

// Import surveys to trigger registration of the survey trigger type
import '../registry/triggers/surveys'
import type { HogFlow } from '../types'
import {
    buildSurveySampleEvent,
    getSampleValueForQuestionType,
    isSurveyTrigger,
    surveyTriggerLogic,
} from './surveyTriggerLogic'

const makeSurvey = (overrides: Partial<Survey> = {}): Survey =>
    ({
        id: `survey-${Math.random().toString(36).slice(2)}`,
        name: 'Test Survey',
        type: 'popover',
        start_date: '2024-01-01T00:00:00Z',
        archived: false,
        ...overrides,
    }) as Survey

const makeSurveys = (count: number, overrides: Partial<Survey> = {}): Survey[] =>
    Array.from({ length: count }, (_, i) => makeSurvey({ name: `Survey ${i + 1}`, ...overrides }))

function makeWorkflow(triggerOverrides?: Record<string, any>): HogFlow {
    const base = {
        id: 'test-workflow',
        actions: [
            {
                id: 'trigger_node',
                type: 'trigger',
                config: { type: 'event', filters: {} },
                ...triggerOverrides,
            },
        ],
        edges: [],
    }
    return base as unknown as HogFlow
}

describe('isSurveyTrigger', () => {
    it.each([
        { name: 'null workflow', workflow: null, expected: false },
        { name: 'undefined workflow', workflow: undefined, expected: false },
        { name: 'workflow with no trigger action', workflow: { ...makeWorkflow(), actions: [] }, expected: false },
        {
            name: 'schedule trigger',
            workflow: makeWorkflow({ config: { type: 'schedule', scheduled_at: '2026-01-01' } }),
            expected: false,
        },
        {
            name: 'event trigger with non-survey event',
            workflow: makeWorkflow({
                config: { type: 'event', filters: { events: [{ id: '$pageview', type: 'events' }] } },
            }),
            expected: false,
        },
        {
            name: 'event trigger with multiple events including survey sent',
            workflow: makeWorkflow({
                config: {
                    type: 'event',
                    filters: {
                        events: [
                            { id: SurveyEventName.SENT, type: 'events' },
                            { id: '$pageview', type: 'events' },
                        ],
                    },
                },
            }),
            expected: false,
        },
        {
            name: 'event trigger with exactly survey sent',
            workflow: makeWorkflow({
                config: { type: 'event', filters: { events: [{ id: SurveyEventName.SENT, type: 'events' }] } },
            }),
            expected: true,
        },
    ])('returns $expected for $name', ({ workflow, expected }) => {
        expect(isSurveyTrigger(workflow as HogFlow | null | undefined)).toBe(expected)
    })
})

describe('getSampleValueForQuestionType', () => {
    it.each([
        { type: SurveyQuestionType.Open, expected: 'User response text' },
        { type: SurveyQuestionType.Rating, expected: '8' },
        { type: SurveyQuestionType.SingleChoice, expected: 'Selected option' },
        { type: SurveyQuestionType.MultipleChoice, expected: ['Option A', 'Option B'] },
        { type: SurveyQuestionType.Link, expected: null },
        { type: 'unknown_type', expected: 'response' },
    ])('returns $expected for $type', ({ type, expected }) => {
        expect(getSampleValueForQuestionType(type)).toEqual(expected)
    })
})

describe('buildSurveySampleEvent', () => {
    const mockGetSampleValue = (type: string): any => {
        switch (type) {
            case SurveyQuestionType.Open:
                return 'text'
            case SurveyQuestionType.Rating:
                return '8'
            case SurveyQuestionType.Link:
                return null
            default:
                return 'response'
        }
    }

    it('uses placeholder values when no survey is selected', () => {
        const result = buildSurveySampleEvent(null, mockGetSampleValue)

        expect(result.event).toBe('survey sent')
        expect(result.properties.$survey_id).toBe('survey-uuid')
        expect(result.properties.$survey_name).toBe('Survey name')
        expect(result.properties.$survey_completed).toBe(true)
    })

    it('uses survey name and id when a survey is selected', () => {
        const survey = makeSurvey({ id: 'abc-123', name: 'NPS Survey' })
        const result = buildSurveySampleEvent(survey, mockGetSampleValue)

        expect(result.properties.$survey_id).toBe('abc-123')
        expect(result.properties.$survey_name).toBe('NPS Survey')
    })

    it('builds per-question response fields for survey with questions', () => {
        const survey = makeSurvey({
            questions: [
                { id: 'q1', type: SurveyQuestionType.Open, question: 'How are you?' },
                {
                    id: 'q2',
                    type: SurveyQuestionType.Rating,
                    question: 'Rate us',
                    display: 'number',
                    scale: 10,
                    lowerBoundLabel: 'Bad',
                    upperBoundLabel: 'Great',
                },
            ] as Survey['questions'],
        })
        const result = buildSurveySampleEvent(survey, mockGetSampleValue)

        expect(result.properties.$survey_response_q1).toBe('text')
        expect(result.properties.$survey_response_q2).toBe('8')
        expect(result.properties.$survey_questions).toEqual([
            { id: 'q1', question: 'How are you?', response: 'text' },
            { id: 'q2', question: 'Rate us', response: '8' },
        ])
    })

    it('skips Link questions in response fields', () => {
        const survey = makeSurvey({
            questions: [
                { id: 'q1', type: SurveyQuestionType.Open, question: 'Feedback?' },
                { id: 'q2', type: SurveyQuestionType.Link, question: 'Visit us', link: 'https://example.com' },
            ] as Survey['questions'],
        })
        const result = buildSurveySampleEvent(survey, mockGetSampleValue)

        expect(result.properties.$survey_response_q1).toBe('text')
        expect(result.properties).not.toHaveProperty('$survey_response_q2')
        // Link questions still appear in $survey_questions array
        expect(result.properties.$survey_questions).toHaveLength(2)
    })

    it('skips questions without an id', () => {
        const survey = makeSurvey({
            questions: [{ type: SurveyQuestionType.Open, question: 'No id question' }] as Survey['questions'],
        })
        const result = buildSurveySampleEvent(survey, mockGetSampleValue)

        const responseKeys = Object.keys(result.properties).filter((k) => k.startsWith('$survey_response_'))
        expect(responseKeys).toHaveLength(0)
    })
})

describe('surveyTriggerLogic', () => {
    let logic: ReturnType<typeof surveyTriggerLogic.build>

    function useSetupMocks({
        surveys = [] as Survey[],
        moreSurveys = [] as Survey[],
        responseCounts = {} as Record<string, number>,
        listError = false,
        moreListError = false,
    } = {}): void {
        let loadMoreCalled = false
        useMocks({
            get: {
                '/api/projects/:team_id/surveys/': (req) => {
                    if (listError) {
                        return [500, { detail: 'Server error' }]
                    }
                    const offset = Number(req.url.searchParams.get('offset') || 0)
                    if (offset > 0) {
                        if (moreListError && !loadMoreCalled) {
                            loadMoreCalled = true
                            return [500, { detail: 'Load more failed' }]
                        }
                        return [200, { results: moreSurveys, count: moreSurveys.length }]
                    }
                    return [200, { results: surveys, count: surveys.length }]
                },
                '/api/projects/:team_id/surveys/responses_count/': () => {
                    return [200, responseCounts]
                },
            },
        })
    }

    beforeEach(() => {
        resetContext({ plugins: [testUtilsPlugin] })
        initKeaTests()
    })

    describe('initial load', () => {
        it('loads surveys on mount', async () => {
            const surveys = makeSurveys(3)
            useSetupMocks({ surveys })

            logic = surveyTriggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSurveys', 'loadSurveysSuccess']).toMatchValues({
                allSurveys: surveys,
                surveysLoading: false,
            })
        })

        it('loads response counts after surveys load', async () => {
            const surveys = makeSurveys(2)
            const responseCounts = { [surveys[0].id]: 10, [surveys[1].id]: 5 }
            useSetupMocks({ surveys, responseCounts })

            logic = surveyTriggerLogic()
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadSurveysSuccess', 'loadResponseCounts', 'loadResponseCountsSuccess'])
                .toMatchValues({
                    responseCounts,
                })
        })
    })

    describe('pagination', () => {
        it('tracks hasMoreSurveys as true when a full page is returned', async () => {
            const surveys = makeSurveys(20)
            useSetupMocks({ surveys })

            logic = surveyTriggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess']).toMatchValues({
                hasMoreSurveys: true,
            })
        })

        it('tracks hasMoreSurveys as false when fewer than a page is returned', async () => {
            const surveys = makeSurveys(5)
            useSetupMocks({ surveys })

            logic = surveyTriggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess']).toMatchValues({
                hasMoreSurveys: false,
            })
        })

        it('appends more surveys on loadMoreSurveys', async () => {
            const firstPage = makeSurveys(20)
            const secondPage = makeSurveys(5)
            useSetupMocks({ surveys: firstPage, moreSurveys: secondPage })

            logic = surveyTriggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess']).toMatchValues({
                allSurveys: firstPage,
            })

            await expectLogic(logic, () => {
                logic.actions.loadMoreSurveys()
            })
                .toDispatchActions(['loadMoreSurveys', 'loadMoreSurveysSuccess'])
                .toMatchValues({
                    allSurveys: [...firstPage, ...secondPage],
                    hasMoreSurveys: false,
                })
        })

        it('sets moreSurveysLoading while loading more', async () => {
            useSetupMocks({ surveys: makeSurveys(20), moreSurveys: makeSurveys(5) })

            logic = surveyTriggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess'])

            await expectLogic(logic, () => {
                logic.actions.loadMoreSurveys()
            })
                .toMatchValues({ moreSurveysLoading: true })
                .toDispatchActions(['loadMoreSurveysSuccess'])
                .toMatchValues({ moreSurveysLoading: false })
        })

        it('reloads response counts after loading more surveys', async () => {
            const firstPage = makeSurveys(20)
            const secondPage = makeSurveys(3)
            useSetupMocks({ surveys: firstPage, moreSurveys: secondPage })

            logic = surveyTriggerLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess', 'loadResponseCountsSuccess'])

            await expectLogic(logic, () => {
                logic.actions.loadMoreSurveys()
            }).toDispatchActions(['loadMoreSurveysSuccess', 'loadResponseCounts'])
        })
    })

    describe('search filtering', () => {
        it('returns all surveys when search term is empty', async () => {
            const surveys = makeSurveys(3)
            useSetupMocks({ surveys })

            logic = surveyTriggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess']).toMatchValues({
                searchTerm: '',
                filteredSurveys: surveys,
            })
        })

        it('filters surveys by name (case-insensitive)', async () => {
            const alpha = makeSurvey({ name: 'Alpha Survey' })
            const beta = makeSurvey({ name: 'Beta Questionnaire' })
            const gamma = makeSurvey({ name: 'gamma survey' })
            useSetupMocks({ surveys: [alpha, beta, gamma] })

            logic = surveyTriggerLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess'])

            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('survey')
            }).toMatchValues({
                searchTerm: 'survey',
                filteredSurveys: [alpha, gamma],
            })
        })

        it('returns empty array when no surveys match search', async () => {
            const surveys = makeSurveys(3)
            useSetupMocks({ surveys })

            logic = surveyTriggerLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess'])

            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('nonexistent')
            }).toMatchValues({
                filteredSurveys: [],
            })
        })

        it('resets filtered results when search term is cleared', async () => {
            const surveys = makeSurveys(3)
            useSetupMocks({ surveys })

            logic = surveyTriggerLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess'])

            logic.actions.setSearchTerm('Survey 1')
            await expectLogic(logic).toMatchValues({
                filteredSurveys: [surveys[0]],
            })

            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('')
            }).toMatchValues({
                filteredSurveys: surveys,
            })
        })
    })

    describe('error handling', () => {
        it('handles loadSurveys failure', async () => {
            useSetupMocks({ listError: true })

            logic = surveyTriggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadSurveys', 'loadSurveysFailure']).toMatchValues({
                allSurveys: [],
                surveysLoading: false,
            })
        })

        it('handles loadMoreSurveys failure', async () => {
            const surveys = makeSurveys(20)
            useSetupMocks({ surveys, moreListError: true })

            logic = surveyTriggerLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess'])

            await expectLogic(logic, () => {
                logic.actions.loadMoreSurveys()
            })
                .toDispatchActions(['loadMoreSurveys', 'loadMoreSurveysFailure'])
                .toMatchValues({
                    moreSurveysLoading: false,
                    allSurveys: surveys,
                })
        })
    })

    describe('response counts', () => {
        it('skips loading response counts when no surveys exist', async () => {
            useSetupMocks({ surveys: [] })

            logic = surveyTriggerLogic()
            logic.mount()

            await expectLogic(logic)
                .toDispatchActions(['loadSurveysSuccess', 'loadResponseCounts', 'loadResponseCountsSuccess'])
                .toMatchValues({
                    responseCounts: {},
                })
        })

        it('loads response counts for all loaded surveys', async () => {
            const surveys = makeSurveys(2)
            const responseCounts = { [surveys[0].id]: 42, [surveys[1].id]: 7 }
            useSetupMocks({ surveys, responseCounts })

            logic = surveyTriggerLogic()
            logic.mount()

            await expectLogic(logic).toDispatchActions(['loadResponseCountsSuccess']).toMatchValues({
                responseCounts,
            })
        })
    })
})
