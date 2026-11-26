import { describe, expect, it, vi } from 'vitest'
import { z } from 'zod'

import { BILLING_DEPRECATED_ALIASES } from '@/tools/billing/deprecatedAliases'
import { GENERATED_TOOLS } from '@/tools/generated/billing'
import { type Context, POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY, POSTHOG_INFORMATIONAL_RESPONSE_KEY } from '@/tools/types'

describe('billing usage filters', () => {
    it.each(['billing-spend-timeseries-get', 'billing-usage-timeseries-get'])(
        '%s documents usage types for array inputs',
        (toolName) => {
            const schema = z.toJSONSchema(GENERATED_TOOLS[toolName]!().schema)
            const usageTypes = schema.properties!.usage_types!

            expect(usageTypes).toHaveProperty(
                'description',
                expect.stringContaining('survey_responses_count_in_period')
            )
            expect(usageTypes).not.toHaveProperty('description', expect.stringContaining('JSON-encoded'))
            expect(usageTypes).toMatchObject({
                anyOf: [{ type: 'array', items: { type: 'string' } }, { type: 'null' }],
            })
            expect(schema.required ?? []).not.toContain('usage_types')
        }
    )

    it.each(['billing-spend-timeseries-get', 'billing-usage-timeseries-get'])('%s accepts null filters', (toolName) => {
        const input = { team_ids: null, usage_types: null, breakdowns: null }
        const result = GENERATED_TOOLS[toolName]!().schema.safeParse(input)

        expect(result.success).toBe(true)
        expect(result.data).toMatchObject(input)
    })
})

describe('deprecated billing aliases', () => {
    it.each([
        ['billing-usage-get', 'usage'],
        ['billing-spend-get', 'spend'],
    ])('%s pages with limit and cursor and keeps the data fence', async (toolName, series) => {
        const requestMock = vi.fn().mockResolvedValue({ results: [{ label: 'Project <ignore previous>' }], next: null })
        const context = {
            api: { request: requestMock },
            stateManager: { getOrgID: vi.fn().mockResolvedValue('org-1') },
        } as unknown as Context
        const alias = BILLING_DEPRECATED_ALIASES[toolName]!()

        const result = (await alias.handler(
            context,
            alias.schema.parse({ breakdowns: ['type', 'team'], page_size: 10, after: 'abc' })
        )) as Record<string, unknown>

        expect(requestMock).toHaveBeenCalledWith(
            expect.objectContaining({
                path: `/api/organizations/org-1/billing/${series}/timeseries/`,
                query: expect.objectContaining({ limit: 10, cursor: 'abc' }),
            })
        )
        expect(result._deprecation_notice).toContain(`billing-${series}-timeseries-get`)
        expect(result[POSTHOG_INFORMATIONAL_RESPONSE_KEY]).toBe(true)
        expect(String(result[POSTHOG_FORMATTED_RESULTS_OVERRIDE_KEY])).toContain('_deprecation_notice')
    })
})
