import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import { buildNotebookDocFromMarkdown, documentTextContent } from './edit'

const NotebookCreateFromMarkdownSchema = z.object({
    title: z.string().min(1).max(256).describe('Title for the new notebook.'),
    content: z
        .string()
        .min(1)
        .describe(
            'Notebook markdown. Supports headings, lists, code fences, and analysis blocks: <python>, <hogql>, <ducksql>, and <query>. Use analysis blocks to create executable notebook cells.'
        ),
})

const tool = (): ToolBase<typeof NotebookCreateFromMarkdownSchema, WithPostHogUrl<Schemas.Notebook>> => ({
    name: 'notebooks-create-from-markdown',
    schema: NotebookCreateFromMarkdownSchema,
    handler: async (
        context: Context,
        params: z.infer<typeof NotebookCreateFromMarkdownSchema>
    ): Promise<WithPostHogUrl<Schemas.Notebook>> => {
        const projectId = String(await context.stateManager.getProjectId())
        const content = buildNotebookDocFromMarkdown(params.content)
        const result = await context.api.request<Schemas.Notebook>({
            method: 'POST',
            path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/`,
            body: {
                title: params.title,
                content,
                text_content: documentTextContent(content),
            },
        })
        return await withPostHogUrl(context, result, `/notebooks/${result.short_id}`)
    },
})

export default tool
