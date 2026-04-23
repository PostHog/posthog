// AUTO-GENERATED from products/billing/mcp/tools.yaml + OpenAPI — do not edit
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { BillingSpendRetrieveQueryParams, BillingUsageRetrieveQueryParams } from '@/generated/billing/api'
import type { Context, ToolBase, ZodObjectAny } from '@/tools/types'

const BillingListSchema = z.object({})

const billingList = (): ToolBase<typeof BillingListSchema, Schemas.PaginatedBillingList> => ({
    name: 'billing-list',
    schema: BillingListSchema,
    // eslint-disable-next-line no-unused-vars
    handler: async (context: Context, params: z.infer<typeof BillingListSchema>) => {
        const result = await context.api.request<Schemas.PaginatedBillingList>({
            method: 'GET',
            path: `/api/billing/`,
        })
        return result
    },
})

const BillingSpendRetrieveSchema = BillingSpendRetrieveQueryParams.extend({
    start_date: BillingSpendRetrieveQueryParams.shape['start_date'].describe(
        'Start date (YYYY-MM-DD), or "all" for earliest available data.'
    ),
    end_date: BillingSpendRetrieveQueryParams.shape['end_date'].describe('End date (YYYY-MM-DD), inclusive.'),
    team_ids: BillingSpendRetrieveQueryParams.shape['team_ids'].describe(
        'Comma-separated team (project) IDs to filter by. Omit for all teams in the org.'
    ),
    breakdowns: BillingSpendRetrieveQueryParams.shape['breakdowns'].describe(
        'Comma-separated dimensions to break down by (e.g. "type", "team"). Omit for a single aggregate series.'
    ),
    interval: BillingSpendRetrieveQueryParams.shape['interval'].describe(
        'Time bucket size, one of "day" or "week". Default "day".'
    ),
})

const billingSpendRetrieve = (): ToolBase<typeof BillingSpendRetrieveSchema, unknown> => ({
    name: 'billing-spend-retrieve',
    schema: BillingSpendRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof BillingSpendRetrieveSchema>) => {
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/billing/spend/`,
            query: {
                breakdowns: params.breakdowns,
                end_date: params.end_date,
                interval: params.interval,
                start_date: params.start_date,
                team_ids: params.team_ids,
                usage_types: params.usage_types,
            },
        })
        return result
    },
})

const BillingUsageRetrieveSchema = BillingUsageRetrieveQueryParams.extend({
    start_date: BillingUsageRetrieveQueryParams.shape['start_date'].describe(
        'Start date (YYYY-MM-DD), or "all" for earliest available data.'
    ),
    end_date: BillingUsageRetrieveQueryParams.shape['end_date'].describe('End date (YYYY-MM-DD), inclusive.'),
    team_ids: BillingUsageRetrieveQueryParams.shape['team_ids'].describe(
        'Comma-separated team (project) IDs to filter by. Omit for all teams in the org.'
    ),
    breakdowns: BillingUsageRetrieveQueryParams.shape['breakdowns'].describe(
        'Comma-separated dimensions to break down by (e.g. "type", "team"). Omit for a single aggregate series.'
    ),
    interval: BillingUsageRetrieveQueryParams.shape['interval'].describe(
        'Time bucket size, one of "day" or "week". Default "day".'
    ),
})

const billingUsageRetrieve = (): ToolBase<typeof BillingUsageRetrieveSchema, unknown> => ({
    name: 'billing-usage-retrieve',
    schema: BillingUsageRetrieveSchema,
    handler: async (context: Context, params: z.infer<typeof BillingUsageRetrieveSchema>) => {
        const result = await context.api.request<unknown>({
            method: 'GET',
            path: `/api/billing/usage/`,
            query: {
                breakdowns: params.breakdowns,
                end_date: params.end_date,
                interval: params.interval,
                start_date: params.start_date,
                team_ids: params.team_ids,
                usage_types: params.usage_types,
            },
        })
        return result
    },
})

export const GENERATED_TOOLS: Record<string, () => ToolBase<ZodObjectAny>> = {
    'billing-list': billingList,
    'billing-spend-retrieve': billingSpendRetrieve,
    'billing-usage-retrieve': billingUsageRetrieve,
}
