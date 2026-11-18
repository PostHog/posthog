import { resetContext } from 'kea'
import { expectLogic, testUtilsPlugin } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
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
        searchResults = [] as Survey[],
        surveysById = {} as Record<string, Survey>,
        responseCounts = {} as Record<string, number>,
        listError = false,
        moreListError = false,
    } = {}): void {
        let loadMoreCalled = false
        useMocks({
            get: {
                '/api/projects/:team_id/surveys/': ({ request }) => {
                    if (listError) {
                        return [500, { detail: 'Server error' }]
                    }
                    const params = new URL(request.url).searchParams
                    if (params.get('search')) {
                        return [200, { results: searchResults, count: searchResults.length }]
                    }
                    const offset = Number(params.get('offset') || 0)
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
                '/api/projects/:team_id/surveys/:id/': ({ params }) => {
                    const survey = surveysById[params.id as string]
                    return survey ? [200, survey] : [404, { detail: 'Not found' }]
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

    describe('search', () => {
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

        it('searches server-side so surveys beyond the loaded pages are reachable', async () => {
            const loaded = makeSurveys(20)
            const oldSurvey = makeSurvey({ name: 'Quarterly product feedback' })
            useSetupMocks({ surveys: loaded, searchResults: [oldSurvey] })

            logic = surveyTriggerLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess'])

            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('NPS')
            })
                .toDispatchActions(['searchSurveys', 'searchSurveysSuccess'])
                .toMatchValues({
                    searchTerm: 'NPS',
                    filteredSurveys: [oldSurvey],
                })
        })

        it('returns empty array when no surveys match search', async () => {
            const surveys = makeSurveys(3)
            useSetupMocks({ surveys, searchResults: [] })

            logic = surveyTriggerLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess'])

            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('nonexistent')
            })
                .toDispatchActions(['searchSurveysSuccess'])
                .toMatchValues({
                    filteredSurveys: [],
                })
        })

        it('resets to the loaded surveys when search term is cleared', async () => {
            const surveys = makeSurveys(3)
            const other = makeSurvey({ name: 'Other' })
            useSetupMocks({ surveys, searchResults: [other] })

            logic = surveyTriggerLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess'])

            logic.actions.setSearchTerm('Other')
            await expectLogic(logic)
                .toDispatchActions(['searchSurveysSuccess'])
                .toMatchValues({
                    filteredSurveys: [other],
                })

            await expectLogic(logic, () => {
                logic.actions.setSearchTerm('')
            }).toMatchValues({
                filteredSurveys: surveys,
            })
        })
    })

    describe('resolving a configured survey by id', () => {
        // A trigger can point at any survey, so the picker has to resolve one outside its loaded pages
        // and tell "still fetching" apart from "deleted" — the banner and the select label both depend on it.
        it.each([
            ['fetches a survey that is not in the loaded pages', true],
            ['records a null entry when the survey no longer exists', false],
        ])('%s', async (_name, exists) => {
            const configured = makeSurvey({ id: 'configured-survey', name: 'Quarterly product feedback' })
            useSetupMocks({
                surveys: makeSurveys(20),
                surveysById: exists ? { 'configured-survey': configured } : {},
            })

            logic = surveyTriggerLogic()
            logic.mount()
            await expectLogic(logic).toDispatchActions(['loadSurveysSuccess'])

            await expectLogic(logic, () => {
                logic.actions.loadSurveyById('configured-survey')
            })
                .toDispatchActions(['loadSurveyByIdSuccess'])
                .toMatchValues({
                    selectedSurveys: { 'configured-survey': exists ? configured : null },
                })

            expect(logic.values.surveysById['configured-survey']).toEqual(exists ? configured : undefined)
        })
    })

    describe('error handling', () => {
        beforeEach(silenceKeaLoadersErrors)
        afterEach(resumeKeaLoadersErrors)

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
