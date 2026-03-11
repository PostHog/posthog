import { z } from 'zod'

import type { Context, ToolBase } from '@/tools/types'

const ModelConfigurationSchema = z.object({
    provider: z.enum(['openai', 'anthropic', 'gemini', 'openrouter', 'fireworks']).describe('LLM provider to use.'),
    model: z.string().describe('Model identifier (e.g. "gpt-4o", "claude-sonnet-4-20250514").'),
    provider_key_id: z.string().uuid().optional().describe('UUID of a stored provider key. Omit to use trial credits.'),
})

const schema = z
    .object({
        name: z.string().max(400).describe('Name of the evaluation.'),
        description: z.string().optional().describe('Description of what this evaluation checks.'),
        enabled: z
            .boolean()
            .optional()
            .describe('Whether the evaluation runs automatically on new generations. Defaults to false.'),
        evaluation_type: z
            .enum(['llm_judge', 'hog'])
            .describe(
                'Type of evaluation. "llm_judge" uses an LLM to score generations against a prompt. "hog" runs deterministic Hog code.'
            ),
        evaluation_config: z
            .object({
                prompt: z
                    .string()
                    .optional()
                    .describe('The prompt for the LLM judge (required when evaluation_type is "llm_judge").'),
                source: z.string().optional().describe('Hog source code (required when evaluation_type is "hog").'),
            })
            .describe('Configuration for the evaluation. Provide "prompt" for llm_judge or "source" for hog type.'),
        output_type: z.literal('boolean').optional().describe('Output type. Currently only "boolean" is supported.'),
        output_config: z
            .object({
                allows_na: z
                    .boolean()
                    .optional()
                    .describe('Whether the evaluation can return N/A for non-applicable generations.'),
            })
            .optional(),
        model_configuration: ModelConfigurationSchema.optional().describe(
            'LLM model configuration (required for llm_judge evaluations).'
        ),
    })
    .superRefine((data, ctx) => {
        if (data.evaluation_type === 'llm_judge') {
            if (!data.evaluation_config.prompt) {
                ctx.addIssue({
                    code: z.ZodIssueCode.custom,
                    message: '"prompt" is required for llm_judge evaluations',
                    path: ['evaluation_config', 'prompt'],
                })
            }
            if (!data.model_configuration) {
                ctx.addIssue({
                    code: z.ZodIssueCode.custom,
                    message: '"model_configuration" is required for llm_judge evaluations',
                    path: ['model_configuration'],
                })
            }
        } else if (data.evaluation_type === 'hog' && !data.evaluation_config.source) {
            ctx.addIssue({
                code: z.ZodIssueCode.custom,
                message: '"source" is required for hog evaluations',
                path: ['evaluation_config', 'source'],
            })
        }
    })

type Params = z.infer<typeof schema>

export const handler: ToolBase<typeof schema>['handler'] = async (context: Context, params: Params) => {
    const projectId = await context.stateManager.getProjectId()

    const result = await context.api.request({
        method: 'POST',
        path: `/api/environments/${projectId}/evaluations/`,
        body: params as unknown as Record<string, unknown>,
    })

    return result
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'evaluation-create',
    schema,
    handler,
})

export default tool
