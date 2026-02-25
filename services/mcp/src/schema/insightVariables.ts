import { z } from 'zod'

// Response schema

export const InsightVariableResponseSchema = z.object({
    id: z.string(),
    name: z.string(),
    type: z.string(),
    default_value: z.any().nullish(),
    created_by: z.any().nullish(),
    created_at: z.string(),
    code_name: z.string().nullish(),
    values: z.any().nullish(),
})

export type InsightVariableResponse = z.infer<typeof InsightVariableResponseSchema>

// Input schemas

export const ListInsightVariablesInputSchema = z.object({
    limit: z.number().int().positive().optional().describe('Maximum number of variables to return'),
    offset: z.number().int().min(0).optional().describe('Number of variables to skip for pagination'),
})

export type ListInsightVariablesInput = z.infer<typeof ListInsightVariablesInputSchema>

export const CreateInsightVariableInputSchema = z.object({
    name: z
        .string()
        .min(1)
        .describe(
            'Name of the variable. This is auto-converted to a code_name (snake_case) used in HogQL queries as {variables.code_name}'
        ),
    type: z.enum(['String', 'Number', 'Boolean', 'List', 'Date']).describe('The data type of the variable'),
    default_value: z
        .any()
        .optional()
        .describe('Default value for the variable when no value is provided at execution time'),
})

export type CreateInsightVariableInput = z.infer<typeof CreateInsightVariableInputSchema>
