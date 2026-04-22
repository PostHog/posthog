import { afterEach, beforeAll, describe, expect, it } from 'vitest'

import {
    type CreatedResources,
    TEST_ORG_ID,
    TEST_PROJECT_ID,
    cleanupResources,
    createTestClient,
    createTestContext,
    generateUniqueKey,
    parseToolResponse,
    setActiveProjectAndOrg,
    validateEnvironmentVariables,
} from '@/shared/test-utils'
import { GENERATED_TOOLS } from '@/tools/generated/surveys'
import type { Context } from '@/tools/types'

describe('Surveys generated tools', { concurrent: false }, () => {
    let context: Context
    const createdResources: CreatedResources = {
        featureFlags: [],
        insights: [],
        dashboards: [],
        surveys: [],
        actions: [],
        cohorts: [],
    }

    beforeAll(async () => {
        validateEnvironmentVariables()
        const client = createTestClient()
        context = createTestContext(client)
        await setActiveProjectAndOrg(context, TEST_PROJECT_ID!, TEST_ORG_ID!)
    })

    afterEach(async () => {
        await cleanupResources(context.api, TEST_PROJECT_ID!, createdResources)
    })

    it('supports full CRUD flow with soft-delete semantics', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()
        const getTool = GENERATED_TOOLS['survey-get']!()
        const updateTool = GENERATED_TOOLS['survey-update']!()
        const deleteTool = GENERATED_TOOLS['survey-delete']!()
        const getAllTool = GENERATED_TOOLS['surveys-get-all']!()

        const createResult = await createTool.handler(context, {
            name: `Generated Survey ${Date.now()}`,
            description: 'Created through generated MCP tool',
            type: 'popover',
            questions: [
                {
                    type: 'open',
                    question: 'What should we improve?',
                },
            ],
        })
        const createdSurvey = parseToolResponse(createResult)
        createdResources.surveys.push(createdSurvey.id)

        const getResult = await getTool.handler(context, { id: createdSurvey.id })
        const fetchedSurvey = parseToolResponse(getResult)
        expect(fetchedSurvey.id).toBe(createdSurvey.id)

        const updateResult = await updateTool.handler(context, {
            id: createdSurvey.id,
            description: 'Updated from integration test',
            questions: [
                {
                    type: 'rating',
                    question: 'How satisfied are you?',
                    display: 'number',
                    scale: 10,
                },
            ],
        })
        const updatedSurvey = parseToolResponse(updateResult)
        expect(updatedSurvey.id).toBe(createdSurvey.id)
        expect(updatedSurvey.description).toBe('Updated from integration test')

        const nonArchivedBeforeArchiveResult = await getAllTool.handler(context, {
            archived: false,
            limit: 100,
            offset: 0,
        })
        const nonArchivedBeforeArchive = parseToolResponse(nonArchivedBeforeArchiveResult)
        expect(nonArchivedBeforeArchive.results.some((survey: { id: string }) => survey.id === createdSurvey.id)).toBe(
            true
        )

        // Delete is a soft-delete (PATCH { archived: true })
        const deleteResult = await deleteTool.handler(context, { id: createdSurvey.id })
        const deletedSurvey = parseToolResponse(deleteResult)
        expect(deletedSurvey.archived).toBe(true)

        // Survey still exists and is retrievable
        const getAfterDeleteResult = await getTool.handler(context, { id: createdSurvey.id })
        const surveyAfterDelete = parseToolResponse(getAfterDeleteResult)
        expect(surveyAfterDelete.archived).toBe(true)

        // Excluded from non-archived list
        const nonArchivedAfterDeleteResult = await getAllTool.handler(context, {
            archived: false,
            limit: 100,
            offset: 0,
        })
        const nonArchivedAfterDelete = parseToolResponse(nonArchivedAfterDeleteResult)
        expect(nonArchivedAfterDelete.results.some((survey: { id: string }) => survey.id === createdSurvey.id)).toBe(
            false
        )

        // Included in archived list
        const archivedAfterDeleteResult = await getAllTool.handler(context, {
            archived: true,
            limit: 100,
            offset: 0,
        })
        const archivedAfterDelete = parseToolResponse(archivedAfterDeleteResult)
        expect(archivedAfterDelete.results.some((survey: { id: string }) => survey.id === createdSurvey.id)).toBe(true)
    })

    it('creates a survey with multiple question types', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()
        const getTool = GENERATED_TOOLS['survey-get']!()

        const createResult = await createTool.handler(context, {
            name: `Multi-Question Survey ${Date.now()}`,
            description: 'Survey with various question types',
            type: 'popover',
            questions: [
                {
                    type: 'open',
                    question: 'Tell us about your experience',
                    optional: false,
                },
                {
                    type: 'rating',
                    question: 'How would you rate our service?',
                    scale: 5,
                    lowerBoundLabel: 'Poor',
                    upperBoundLabel: 'Excellent',
                    display: 'number',
                },
                {
                    type: 'single_choice',
                    question: 'Which feature do you use most?',
                    choices: ['Analytics', 'Feature Flags', 'Session Replay', 'Surveys'],
                },
                {
                    type: 'multiple_choice',
                    question: 'What improvements would you like to see?',
                    choices: ['Better UI', 'More integrations', 'Faster performance', 'Better docs'],
                    hasOpenChoice: true,
                },
            ],
        })
        const createdSurvey = parseToolResponse(createResult)
        createdResources.surveys.push(createdSurvey.id)

        const getResult = await getTool.handler(context, { id: createdSurvey.id })
        const surveyData = parseToolResponse(getResult)

        expect(surveyData.questions).toHaveLength(4)
        expect(surveyData.questions[0].type).toBe('open')
        expect(surveyData.questions[1].type).toBe('rating')
        expect(surveyData.questions[2].type).toBe('single_choice')
        expect(surveyData.questions[3].type).toBe('multiple_choice')
    })

    it('creates an NPS survey with branching logic', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()
        const getTool = GENERATED_TOOLS['survey-get']!()

        const createResult = await createTool.handler(context, {
            name: `NPS Survey ${Date.now()}`,
            description: 'Net Promoter Score survey with follow-up questions',
            type: 'popover',
            questions: [
                {
                    type: 'rating',
                    question: 'How likely are you to recommend our product to a friend or colleague?',
                    scale: 10,
                    display: 'number',
                    lowerBoundLabel: 'Not at all likely',
                    upperBoundLabel: 'Extremely likely',
                    branching: {
                        type: 'response_based',
                        responseValues: {
                            detractors: 1,
                            promoters: 2,
                        },
                    },
                },
                {
                    type: 'open',
                    question: 'What could we do to improve your experience?',
                },
                {
                    type: 'open',
                    question: 'What do you love most about our product?',
                },
                {
                    type: 'open',
                    question: 'Thank you for your feedback!',
                },
            ],
        })
        const createdSurvey = parseToolResponse(createResult)
        createdResources.surveys.push(createdSurvey.id)

        const getResult = await getTool.handler(context, { id: createdSurvey.id })
        const surveyData = parseToolResponse(getResult)

        expect(surveyData.questions).toHaveLength(4)
        expect(surveyData.questions[0].branching).toBeTruthy()
        expect(surveyData.questions[0].branching.type).toBe('response_based')
    })

    it('creates a survey with targeting filters', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()
        const getTool = GENERATED_TOOLS['survey-get']!()

        const createResult = await createTool.handler(context, {
            name: `Targeted Survey ${Date.now()}`,
            description: 'Survey with user targeting',
            type: 'popover',
            questions: [
                {
                    type: 'open',
                    question: 'How satisfied are you with our premium features?',
                },
            ],
            targeting_flag_filters: {
                groups: [
                    {
                        properties: [
                            {
                                key: 'subscription',
                                value: 'premium',
                                operator: 'exact',
                                type: 'person',
                            },
                        ],
                        rollout_percentage: 100,
                    },
                ],
            },
        })
        const createdSurvey = parseToolResponse(createResult)
        createdResources.surveys.push(createdSurvey.id)

        const getResult = await getTool.handler(context, { id: createdSurvey.id })
        const surveyData = parseToolResponse(getResult)

        expect(surveyData.targeting_flag).toBeTruthy()
    })

    it('returns error for non-existent survey ID', async () => {
        const getTool = GENERATED_TOOLS['survey-get']!()
        const nonExistentId = generateUniqueKey('non-existent')

        await expect(getTool.handler(context, { id: nonExistentId })).rejects.toThrow()
    })

    it('returns error when deleting a non-existent survey', async () => {
        const deleteTool = GENERATED_TOOLS['survey-delete']!()

        await expect(deleteTool.handler(context, { id: generateUniqueKey('non-existent') })).rejects.toThrow()
    })

    it('lists and searches surveys', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()
        const getAllTool = GENERATED_TOOLS['surveys-get-all']!()

        const timestamp = Date.now()
        const testSurveys = []
        for (let i = 0; i < 3; i++) {
            const result = await createTool.handler(context, {
                name: `List Test Survey ${timestamp}-${i}`,
                description: `Test survey ${i} for listing`,
                type: 'popover',
                questions: [{ type: 'open', question: `Test question ${i}` }],
            })
            const survey = parseToolResponse(result)
            testSurveys.push(survey)
            createdResources.surveys.push(survey.id)
        }

        const listResult = await getAllTool.handler(context, { limit: 100, offset: 0 })
        const allSurveys = parseToolResponse(listResult)
        expect(allSurveys.results.length).toBeGreaterThanOrEqual(3)
        for (const testSurvey of testSurveys) {
            expect(allSurveys.results.some((s: { id: string }) => s.id === testSurvey.id)).toBe(true)
        }

        const uniqueName = `Unique Search Survey ${timestamp}`
        const searchSurveyResult = await createTool.handler(context, {
            name: uniqueName,
            type: 'popover',
            questions: [{ type: 'open', question: 'Search test question' }],
        })
        const searchSurvey = parseToolResponse(searchSurveyResult)
        createdResources.surveys.push(searchSurvey.id)

        const searchResult = await getAllTool.handler(context, { search: `Unique Search Survey ${timestamp}` })
        const searchResults = parseToolResponse(searchResult)
        expect(searchResults.results.some((s: { id: string }) => s.id === searchSurvey.id)).toBe(true)
    })

    it('updates appearance, questions, and conditions', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()
        const updateTool = GENERATED_TOOLS['survey-update']!()
        const getTool = GENERATED_TOOLS['survey-get']!()

        const createResult = await createTool.handler(context, {
            name: `Update Test Survey ${Date.now()}`,
            description: 'Original description',
            type: 'popover',
            questions: [{ type: 'open', question: 'Original question' }],
            appearance: {
                backgroundColor: '#ffffff',
                textColor: '#000000',
            },
        })
        const createdSurvey = parseToolResponse(createResult)
        createdResources.surveys.push(createdSurvey.id)

        await updateTool.handler(context, {
            id: createdSurvey.id,
            name: `Updated Survey ${Date.now()}`,
            description: 'Updated description with new content',
            questions: [
                {
                    type: 'rating',
                    question: 'How would you rate our service?',
                    scale: 10,
                    display: 'number',
                    lowerBoundLabel: 'Poor',
                    upperBoundLabel: 'Excellent',
                },
            ],
            appearance: {
                backgroundColor: '#f0f0f0',
                textColor: '#333333',
                submitButtonColor: '#007bff',
                submitButtonText: 'Submit Feedback',
            },
            conditions: {
                url: 'https://example.com/product',
                urlMatchType: 'icontains',
                deviceTypes: ['Desktop', 'Mobile'],
                deviceTypesMatchType: 'exact',
            },
        })

        const getResult = await getTool.handler(context, { id: createdSurvey.id })
        const updatedSurvey = parseToolResponse(getResult)

        expect(updatedSurvey.name).toContain('Updated Survey')
        expect(updatedSurvey.description).toBe('Updated description with new content')
        expect(updatedSurvey.questions).toHaveLength(1)
        expect(updatedSurvey.questions[0].type).toBe('rating')
        expect(updatedSurvey.questions[0].scale).toBe(10)
        expect(updatedSurvey.appearance.backgroundColor).toBe('#f0f0f0')
        expect(updatedSurvey.appearance.submitButtonColor).toBe('#007bff')
        expect(updatedSurvey.conditions.url).toBe('https://example.com/product')
        expect(updatedSurvey.conditions.urlMatchType).toBe('icontains')
        expect(updatedSurvey.conditions.deviceTypes).toEqual(['Desktop', 'Mobile'])
    })

    it('updates targeting and scheduling', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()
        const updateTool = GENERATED_TOOLS['survey-update']!()
        const getTool = GENERATED_TOOLS['survey-get']!()

        const createResult = await createTool.handler(context, {
            name: `Scheduling Test Survey ${Date.now()}`,
            description: 'Testing targeting and scheduling',
            type: 'popover',
            questions: [{ type: 'open', question: 'Scheduled question' }],
        })
        const createdSurvey = parseToolResponse(createResult)
        createdResources.surveys.push(createdSurvey.id)

        await updateTool.handler(context, {
            id: createdSurvey.id,
            targeting_flag_filters: {
                groups: [
                    {
                        properties: [
                            {
                                type: 'person',
                                key: 'email',
                                value: '@company.com',
                                operator: 'icontains',
                            },
                            {
                                type: 'person',
                                key: 'plan',
                                value: ['premium', 'enterprise'],
                                operator: 'exact',
                            },
                        ],
                        rollout_percentage: 75,
                    },
                ],
            },
            schedule: 'recurring',
            iteration_count: 3,
            iteration_frequency_days: 7,
            responses_limit: 100,
        })

        const getResult = await getTool.handler(context, { id: createdSurvey.id })
        const updatedSurvey = parseToolResponse(getResult)

        expect(updatedSurvey.targeting_flag).toBeTruthy()
        expect(updatedSurvey.targeting_flag.filters.groups).toHaveLength(1)
        expect(updatedSurvey.targeting_flag.filters.groups[0].properties).toHaveLength(2)
        expect(updatedSurvey.targeting_flag.filters.groups[0].rollout_percentage).toBe(75)
        expect(updatedSurvey.schedule).toBe('recurring')
        expect(updatedSurvey.iteration_count).toBe(3)
        expect(updatedSurvey.iteration_frequency_days).toBe(7)
        expect(updatedSurvey.responses_limit).toBe(100)
    })

    it('retrieves survey and global stats without date filters', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()
        const surveyStatsTool = GENERATED_TOOLS['survey-stats']!()
        const globalStatsTool = GENERATED_TOOLS['surveys-global-stats']!()

        const createResult = await createTool.handler(context, {
            name: `Stats No Filter Survey ${Date.now()}`,
            type: 'popover',
            questions: [{ type: 'rating', question: 'Rate us', display: 'number', scale: 5 }],
        })
        const survey = parseToolResponse(createResult)
        createdResources.surveys.push(survey.id)

        const statsResult = await surveyStatsTool.handler(context, { id: survey.id })
        const stats = parseToolResponse(statsResult)
        expect(stats.survey_id).toBe(survey.id)
        expect(stats.stats).toBeTruthy()

        const globalResult = await globalStatsTool.handler(context, {})
        const globalStats = parseToolResponse(globalResult)
        expect(globalStats.stats).toBeTruthy()
    })

    it('supports survey and global stats date filters', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()
        const surveyStatsTool = GENERATED_TOOLS['survey-stats']!()
        const globalStatsTool = GENERATED_TOOLS['surveys-global-stats']!()

        const createResult = await createTool.handler(context, {
            name: `Stats Survey ${Date.now()}`,
            type: 'popover',
            questions: [
                {
                    type: 'rating',
                    question: 'Rate the setup',
                    display: 'number',
                    scale: 5,
                },
            ],
        })
        const createdSurvey = parseToolResponse(createResult)
        createdResources.surveys.push(createdSurvey.id)

        const surveyStatsResult = await surveyStatsTool.handler(context, {
            id: createdSurvey.id,
            date_from: '2024-01-01T00:00:00Z',
            date_to: '2024-12-31T23:59:59Z',
        })
        const surveyStats = parseToolResponse(surveyStatsResult)

        expect(surveyStats.survey_id).toBe(createdSurvey.id)
        expect(surveyStats.stats).toBeTruthy()
        expect(surveyStats.rates).toBeTruthy()

        const globalStatsResult = await globalStatsTool.handler(context, {
            date_from: '2024-01-01T00:00:00Z',
            date_to: '2024-12-31T23:59:59Z',
        })
        const globalStats = parseToolResponse(globalStatsResult)

        expect(globalStats.stats).toBeTruthy()
        expect(globalStats.rates).toBeTruthy()
    })

    it('links and verifies a feature flag on a survey', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()
        const updateTool = GENERATED_TOOLS['survey-update']!()
        const getTool = GENERATED_TOOLS['survey-get']!()

        const projectId = await context.stateManager.getProjectId()
        const flag = await context.api.request<{ id: number }>({
            method: 'POST',
            path: `/api/projects/${projectId}/feature_flags/`,
            body: {
                key: `survey-test-flag-${Date.now()}`,
                name: 'Survey test flag',
                filters: { groups: [{ properties: [], rollout_percentage: 100 }] },
                active: true,
            },
        })
        createdResources.featureFlags.push(flag.id)

        const createResult = await createTool.handler(context, {
            name: `Flag Link Survey ${Date.now()}`,
            type: 'popover',
            questions: [{ type: 'open', question: 'Flag-based question' }],
        })
        const survey = parseToolResponse(createResult)
        createdResources.surveys.push(survey.id)

        await updateTool.handler(context, { id: survey.id, linked_flag_id: flag.id })

        const getResult = await getTool.handler(context, { id: survey.id })
        const updated = parseToolResponse(getResult)
        expect(updated.linked_flag_id).toBe(flag.id)
    })

    it('adds and changes question types including emoji display and open choice', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()
        const updateTool = GENERATED_TOOLS['survey-update']!()
        const getTool = GENERATED_TOOLS['survey-get']!()

        const createResult = await createTool.handler(context, {
            name: `Question Types Survey ${Date.now()}`,
            type: 'popover',
            questions: [{ type: 'open', question: 'Original question' }],
        })
        const survey = parseToolResponse(createResult)
        createdResources.surveys.push(survey.id)

        await updateTool.handler(context, {
            id: survey.id,
            questions: [
                {
                    type: 'single_choice',
                    question: 'Which option?',
                    choices: ['A', 'B', 'C', 'Other'],
                    hasOpenChoice: true,
                },
                {
                    type: 'multiple_choice',
                    question: 'Select all:',
                    choices: ['Feature 1', 'Feature 2', 'Feature 3'],
                },
                {
                    type: 'rating',
                    question: 'Rate your experience',
                    scale: 5,
                    display: 'emoji',
                },
            ],
        })

        const getResult = await getTool.handler(context, { id: survey.id })
        const updated = parseToolResponse(getResult)

        expect(updated.questions).toHaveLength(3)
        expect(updated.questions[0].type).toBe('single_choice')
        expect(updated.questions[0].hasOpenChoice).toBe(true)
        expect(updated.questions[1].type).toBe('multiple_choice')
        expect(updated.questions[2].type).toBe('rating')
        expect(updated.questions[2].display).toBe('emoji')
    })

    it('accepts branching on open questions (backend does not validate response keys)', async () => {
        const createTool = GENERATED_TOOLS['survey-create']!()

        const result = await createTool.handler(context, {
            name: `Branching Open ${Date.now()}`,
            type: 'popover',
            questions: [
                {
                    type: 'open',
                    question: 'How was this?',
                    branching: {
                        type: 'response_based',
                        responseValues: { invalid: 'end' },
                    },
                },
            ],
        })

        const survey = parseToolResponse(result)
        expect(survey.id).toBeTruthy()
        expect(survey.questions[0].branching.type).toBe('response_based')
    })
})
