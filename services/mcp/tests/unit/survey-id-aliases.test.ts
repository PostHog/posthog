import { describe, expect, it } from 'vitest'
import { z } from 'zod'

import { GENERATED_TOOLS as SURVEY_TOOLS } from '@/tools/generated/surveys'

const SURVEY_ID = '0199a1c0-0000-7000-8000-000000000000'
const OTHER_ID = '0199a1c0-0000-7000-8000-000000000001'

// Derived from the generated tools, so a new id-taking survey tool cannot ship without the aliases.
const SURVEY_ID_TOOLS = Object.entries(SURVEY_TOOLS)
    .filter(([, factory]) => {
        const json = z.toJSONSchema(factory().schema, { io: 'input', reused: 'inline' }) as {
            properties?: Record<string, unknown>
        }
        return Boolean(json.properties?.id)
    })
    .map(([name]) => name)
    .sort()

describe('survey id aliases', () => {
    it('finds the survey tools that take an id', () => {
        expect(SURVEY_ID_TOOLS).toEqual(
            expect.arrayContaining(['survey-get', 'survey-stats', 'survey-update', 'surveys-responses-list'])
        )
    })

    describe.each(SURVEY_ID_TOOLS)('%s', (toolName) => {
        const schema = SURVEY_TOOLS[toolName]!().schema

        it.each([
            ['id', { id: SURVEY_ID }],
            ['survey_id', { survey_id: SURVEY_ID }],
            ['surveyId', { surveyId: SURVEY_ID }],
            ['id over aliases on conflict', { id: SURVEY_ID, survey_id: OTHER_ID, surveyId: OTHER_ID }],
        ])('accepts %s', (_label, input) => {
            const result = schema.safeParse(input)
            expect(result.success, JSON.stringify(result.error?.issues)).toBe(true)
            const data = result.data as Record<string, unknown>
            expect(data.id).toEqual(SURVEY_ID)
            expect(data).not.toHaveProperty('survey_id')
            expect(data).not.toHaveProperty('surveyId')
        })

        it('still rejects a call with no identifier', () => {
            expect(schema.safeParse({}).success).toBe(false)
        })
    })
})
