import { SurveyEventName } from '~/types'

import { getSelectedSurveyId, isSurveyTriggerConfig } from './surveys'

describe('surveys', () => {
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
})
