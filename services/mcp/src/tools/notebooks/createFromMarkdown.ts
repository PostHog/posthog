import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import {
    buildNotebookDocFromMarkdown,
    contentUsesExecutableAnalysisBlocks,
    documentTextContent,
    hasNotebookPythonFeatureFlag,
} from './edit'

const NotebookCreateFromMarkdownSchema = z.object({
    title: z.string().min(1).max(256).describe('Title for the new notebook.'),
    content: z
        .string()
        .min(1)
        .describe(
            'Notebook markdown. Supports headings, lists, code fences, and <query> blocks for old-style query nodes. Prefer <query> blocks for SQL analysis.'
        ),
})

const tool = (): ToolBase<typeof NotebookCreateFromMarkdownSchema, WithPostHogUrl<Schemas.Notebook>> => ({
    name: 'notebooks-create-from-markdown',
    schema: NotebookCreateFromMarkdownSchema,
    handler: async (
        context: Context,
        params: z.infer<typeof NotebookCreateFromMarkdownSchema>
    ): Promise<WithPostHogUrl<Schemas.Notebook>> => {
        if (contentUsesExecutableAnalysisBlocks(params.content) && !(await hasNotebookPythonFeatureFlag(context))) {
            throw new Error(
                'Python, HogQL SQL, and DuckDB SQL notebook cells require the notebook-python feature flag. Use <query> nodes or saved insights for SQL analysis instead.'
            )
        }

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
