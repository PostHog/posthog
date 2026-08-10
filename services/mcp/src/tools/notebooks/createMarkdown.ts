import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import { buildMarkdownNotebookContent } from './markdownDoc'

export const NotebooksCreateMarkdownSchema = z
    .object({
        title: z.string().min(1).max(256).describe('Notebook title. Becomes the leading `# heading` of the document.'),
        markdown: z
            .string()
            .optional()
            .describe(
                'Optional initial markdown body below the title. Do not include executable cells here — add them with notebooks-add-cell.'
            ),
        tags: z
            .array(z.string().min(1).max(255))
            .max(100)
            .optional()
            .describe(
                'Optional organizational tags for the notebook (e.g. ["experiments-sme", "investigation"]). Tags make notebooks discoverable via the tags filter on notebooks-list.'
            ),
    })
    .strict()

type CreateMarkdownResult = WithPostHogUrl<{ notebook_id: string; title: string }>

export const createMarkdownHandler: ToolBase<
    typeof NotebooksCreateMarkdownSchema,
    CreateMarkdownResult
>['handler'] = async (context: Context, params: z.infer<typeof NotebooksCreateMarkdownSchema>) => {
    const projectId = await context.stateManager.getProjectId()
    const body = params.markdown?.trim() ? `\n\n${params.markdown.trim()}` : ''
    const markdown = `# ${params.title}${body}`
    const notebook = await context.api.request<Schemas.Notebook>({
        method: 'POST',
        path: `/api/projects/${encodeURIComponent(projectId)}/notebooks/`,
        body: {
            title: params.title,
            content: buildMarkdownNotebookContent(markdown),
            text_content: markdown,
            ...(params.tags?.length ? { tags: params.tags } : {}),
        },
    })
    return await withPostHogUrl(
        context,
        { notebook_id: notebook.short_id, title: params.title },
        `/notebooks/${notebook.short_id}`
    )
}

const tool = (): ToolBase<typeof NotebooksCreateMarkdownSchema, CreateMarkdownResult> => ({
    name: 'notebooks-create-markdown',
    schema: NotebooksCreateMarkdownSchema,
    handler: createMarkdownHandler,
})

export default tool
