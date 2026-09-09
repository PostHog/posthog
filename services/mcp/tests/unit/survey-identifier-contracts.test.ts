import { describe, expect, it } from 'vitest'

import { GENERATED_TOOLS } from '@/tools/generated/surveys'

describe('survey identifiers', () => {
    it.each([
        'survey-get',
        'survey-update',
        'survey-delete',
        'survey-launch',
        'survey-stop',
        'survey-stats',
        'surveys-responses-list',
        'surveys-summarize-responses-create',
    ])('%s accepts survey identifier spellings without changing the canonical id', (toolName) => {
        const schema = GENERATED_TOOLS[toolName]!().schema
        const id = '0190a1b2-c3d4-7e8f-9012-3456789abcde'

        for (const key of ['id', 'surveyId', 'survey_id']) {
            const result = schema.parse({ [key]: id }) as Record<string, unknown>
            expect(result.id).toBe(id)
            expect(result).not.toHaveProperty('surveyId')
            expect(result).not.toHaveProperty('survey_id')
        }

        expect(schema.parse({ id, surveyId: '0190a1b2-c3d4-7e8f-9012-3456789abcdf' })).toMatchObject({ id })
        expect(schema.safeParse({}).success).toBe(false)
        expect(schema.safeParse({ surveyId: 42 }).success).toBe(false)
    })
})
