import { resetContext } from 'kea'
import { expectLogic, testUtilsPlugin } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { Survey } from '~/types'

import { surveyTriggerLogic } from './surveyTriggerLogic'

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
