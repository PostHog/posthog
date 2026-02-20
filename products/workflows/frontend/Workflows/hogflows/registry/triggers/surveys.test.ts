import { SurveyEventName } from '~/types'

import { getSelectedSurveyId, isSurveyTriggerConfig } from './surveys'
import { getRegisteredTriggerTypes } from './triggerTypeRegistry'

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
                config: { type: 'schedule', scheduled_at: '2026-01-01' },
                expected: null,
            },
        ])('returns $expected for $name', ({ config, expected }) => {
            const surveyType = getSurveyTriggerType()
            expect(surveyType.validate!(config as any)).toEqual(expected)
        })
    })
})
