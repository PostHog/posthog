import { Survey, SurveyEventName, SurveyQuestionType } from '~/types'

import {
    buildProperties,
    getSelectedSurveyId,
    getSurveyResponsePropertyKeys,
    getUserProperties,
    isSurveyTriggerConfig,
} from './surveys'
import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

// Partial mock — getSurveyResponsePropertyKeys only accesses survey.questions
const makeSurvey = (questions: { question: string; type: SurveyQuestionType }[]): Survey =>
    ({ questions: questions.map((q) => ({ ...q, id: 'q-id' })) }) as unknown as Survey

describe('surveys', () => {
    const getSurveyTriggerType = (): ReturnType<typeof getRegisteredTriggerTypes>[number] => {
        const types = getRegisteredTriggerTypes()
        const surveyType = types.find((t) => t.value === 'survey_response')
        if (!surveyType) {
            throw new Error('Survey trigger type not registered')
        }
        return surveyType
    }
    describe('isSurveyTriggerConfig', () => {
        it.each([
            {
                name: 'survey sent event',
                config: { type: 'event', filters: { events: [{ id: SurveyEventName.SENT }] } },
                expected: true,
            },
            {
                name: 'non-event config type',
                config: { type: 'webhook', filters: { events: [{ id: SurveyEventName.SENT }] } },
                expected: false,
            },
            {
                name: 'different event id',
                config: { type: 'event', filters: { events: [{ id: '$pageview' }] } },
                expected: false,
            },
            {
                name: 'multiple events',
                config: {
                    type: 'event',
                    filters: { events: [{ id: SurveyEventName.SENT }, { id: '$pageview' }] },
                },
                expected: false,
            },
            {
                name: 'no events',
                config: { type: 'event', filters: {} },
                expected: false,
            },
            {
                name: 'empty events array',
                config: { type: 'event', filters: { events: [] } },
                expected: false,
            },
        ])('returns $expected for $name', ({ config, expected }) => {
            expect(isSurveyTriggerConfig(config as any)).toBe(expected)
        })
    })

    describe('getSelectedSurveyId', () => {
        it.each([
            {
                name: 'specific survey id',
                config: {
                    type: 'event',
                    filters: {
                        properties: [{ key: '$survey_id', value: 'survey-123', operator: 'exact' }],
                    },
                },
                expected: 'survey-123',
            },
            {
                name: '"any" survey (is_set operator)',
                config: {
                    type: 'event',
                    filters: {
                        properties: [{ key: '$survey_id', operator: 'is_set' }],
                    },
                },
                expected: 'any',
            },
            {
                name: 'no survey_id property',
                config: {
                    type: 'event',
                    filters: { properties: [] },
                },
                expected: null,
            },
            {
                name: 'non-event config type',
                config: { type: 'webhook', filters: {} },
                expected: null,
            },
            {
                name: 'no properties at all',
                config: { type: 'event', filters: {} },
                expected: null,
            },
            {
                name: 'survey_id property with no value',
                config: {
                    type: 'event',
                    filters: {
                        properties: [{ key: '$survey_id', operator: 'exact' }],
                    },
                },
                expected: null,
            },
        ])('returns $expected for $name', ({ config, expected }) => {
            expect(getSelectedSurveyId(config as any)).toBe(expected)
        })
    })

    describe('validate', () => {
        it.each([
            {
                name: 'no $survey_id property',
                config: {
                    type: 'event',
                    filters: {
                        events: [{ id: SurveyEventName.SENT }],
                        properties: [],
                    },
                },
                expected: { valid: false, errors: { filters: 'Please select a survey' } },
            },
            {
                name: 'specific survey selected',
                config: {
                    type: 'event',
                    filters: {
                        events: [{ id: SurveyEventName.SENT }],
                        properties: [{ key: '$survey_id', value: 'survey-123', operator: 'exact' }],
                    },
                },
                expected: { valid: true, errors: {} },
            },
            {
                name: 'any survey (is_set)',
                config: {
                    type: 'event',
                    filters: {
                        events: [{ id: SurveyEventName.SENT }],
                        properties: [{ key: '$survey_id', operator: 'is_set' }],
                    },
                },
                expected: { valid: true, errors: {} },
            },
            {
                name: 'non-event config',
                config: { type: 'schedule' },
                expected: null,
            },
        ])('returns $expected for $name', ({ config, expected }) => {
            const surveyType = getSurveyTriggerType()
            expect(surveyType.validate!(config as any)).toEqual(expected)
        })
    })

    it('buildConfig produces a config recognized by matchConfig', () => {
        const surveyType = getSurveyTriggerType()
        const config = surveyType.buildConfig()
        expect(surveyType.matchConfig!(config)).toBe(true)
    })

    describe('getUserProperties', () => {
        it.each([
            {
                name: 'filters out managed properties',
                config: {
                    type: 'event' as const,
                    filters: {
                        properties: [
                            { key: '$survey_id', value: 'survey-123', operator: 'exact', type: 'event' },
                            { key: '$survey_completed', value: true, operator: 'exact', type: 'event' },
                            { key: '$survey_response', value: '5', operator: 'exact', type: 'event' },
                            { key: '$survey_response_1', value: 'price', operator: 'exact', type: 'event' },
                        ],
                    },
                },
                expected: [
                    { key: '$survey_response', value: '5', operator: 'exact', type: 'event' },
                    { key: '$survey_response_1', value: 'price', operator: 'exact', type: 'event' },
                ],
            },
            {
                name: 'returns empty array when no properties',
                config: { type: 'event' as const, filters: {} },
                expected: [],
            },
        ])('$name', ({ config, expected }) => {
            expect(getUserProperties(config)).toEqual(expected)
        })
    })

    describe('buildProperties', () => {
        it.each([
            {
                name: 'specific survey with user properties',
                surveyId: 'survey-123' as string | null | 'any',
                completedOnly: false,
                userProps: [{ key: '$survey_response', value: '5', operator: 'exact', type: 'event' }],
                expected: [
                    { key: '$survey_id', value: 'survey-123', operator: 'exact', type: 'event' },
                    { key: '$survey_response', value: '5', operator: 'exact', type: 'event' },
                ],
            },
            {
                name: '"any" survey with completed filter',
                surveyId: 'any' as string | null | 'any',
                completedOnly: true,
                userProps: [],
                expected: [
                    { key: '$survey_id', operator: 'is_set', type: 'event' },
                    { key: '$survey_completed', value: true, operator: 'exact', type: 'event' },
                ],
            },
            {
                name: 'no survey selected',
                surveyId: null as string | null | 'any',
                completedOnly: false,
                userProps: [],
                expected: [],
            },
        ])('$name', ({ surveyId, completedOnly, userProps, expected }) => {
            expect(buildProperties(surveyId, completedOnly, userProps)).toEqual(expected)
        })
    })

    describe('getSurveyResponsePropertyKeys', () => {
        it('generates correct keys for multiple questions', () => {
            const survey = makeSurvey([
                { question: 'How likely are you to recommend us?', type: SurveyQuestionType.Rating },
                { question: 'What can we improve?', type: SurveyQuestionType.Open },
            ])
            const result = getSurveyResponsePropertyKeys(survey)
            expect(result).toEqual([
                {
                    key: '$survey_response',
                    buttonLabel: 'How likely are you to recommend us?',
                    question: 'How likely are you to recommend us?',
                },
                { key: '$survey_response_1', buttonLabel: 'What can we improve?', question: 'What can we improve?' },
            ])
        })

        it('skips link questions but preserves indices', () => {
            const survey = makeSurvey([
                { question: 'Rate us', type: SurveyQuestionType.Rating },
                { question: 'Visit our site', type: SurveyQuestionType.Link },
                { question: 'Any feedback?', type: SurveyQuestionType.Open },
            ])
            const result = getSurveyResponsePropertyKeys(survey)
            expect(result).toEqual([
                { key: '$survey_response', buttonLabel: 'Rate us', question: 'Rate us' },
                { key: '$survey_response_2', buttonLabel: 'Any feedback?', question: 'Any feedback?' },
            ])
        })

        it('truncates long question text', () => {
            const survey = makeSurvey([
                {
                    question: 'This is a very long question that should be truncated at forty characters',
                    type: SurveyQuestionType.Open,
                },
            ])
            const result = getSurveyResponsePropertyKeys(survey)
            expect(result[0].buttonLabel).toBe('This is a very long question that shoul...')
            expect(result[0].question).toBe('This is a very long question that should be truncated at forty characters')
        })
    })
})
