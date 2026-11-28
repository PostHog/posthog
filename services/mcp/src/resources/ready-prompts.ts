import { parse as parseYaml } from 'yaml'
import { z } from 'zod'

import type { PromptResource } from './manifest-types'

// The fields a product's `mcp/ready_prompts/prompts.yaml` declares. `tools` and `answer_shape`
// are for the product's eval suite and reviewers; clients only see the name, title, description,
// arguments and message text.
const ReadyPromptSchema = z.object({
    name: z.string().regex(/^[a-z0-9]+(-[a-z0-9]+)*$/),
    title: z.string().min(1),
    description: z.string().min(1),
    tools: z.array(z.string()).min(1),
    answer_shape: z.string().min(1),
    arguments: z
        .array(z.object({ name: z.string().min(1), description: z.string().min(1), required: z.boolean() }))
        .optional(),
    text: z.string().min(1),
})

const ReadyPromptsFileSchema = z.object({ prompts: z.array(ReadyPromptSchema).min(1) })

export function parseReadyPrompts(yamlText: string): PromptResource[] {
    const { prompts } = ReadyPromptsFileSchema.parse(parseYaml(yamlText))
    return prompts.map((prompt) => ({
        id: prompt.name,
        name: prompt.name,
        title: prompt.title,
        description: prompt.description,
        ...(prompt.arguments ? { arguments: prompt.arguments } : {}),
        messages: [{ role: 'user', content: { type: 'text', text: prompt.text.trimEnd() } }],
    }))
}

// Keep in step with `render_ready_prompt` in products/web_analytics/evals/ready_prompts.py,
// which builds the eval cases from the same file.
export function appendPromptArguments(
    text: string,
    declared: PromptResource['arguments'],
    args: Record<string, unknown> | undefined
): string {
    const lines = (declared ?? []).flatMap(({ name }) => {
        const value = args?.[name]
        return typeof value === 'string' && value.trim() !== '' ? [`${name}: ${value.trim()}`] : []
    })
    return lines.length ? `${text}\n\n${lines.join('\n')}` : text
}
