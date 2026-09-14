import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import { withPostHogUrl, type WithPostHogUrl } from '@/tools/tool-utils'
import type { Context, ToolBase } from '@/tools/types'

import { createMarkdownNotebook } from './createMarkdown'

// Strict, so a caller that still sends the ProseMirror `content` of the old contract gets a
// validation error instead of a notebook that silently holds only its title.
export const NotebooksCreateSchema = z
    .object({
        title: z.string().min(1).max(256).describe('Notebook title. Becomes the leading `# heading` of the document.'),
        markdown: z
            .string()
            .optional()
            .describe(
                'Markdown body below the title: headings, lists, tables, fenced code, and component tags such as `<Query ... />`. Start at the first section, because the title is already the heading.'
            ),
    })
    .strict()

type CreateNotebookResult = WithPostHogUrl<Schemas.Notebook>

export const createNotebookHandler: ToolBase<typeof NotebooksCreateSchema, CreateNotebookResult>['handler'] = async (
    context: Context,
    params: z.infer<typeof NotebooksCreateSchema>
) => {
    const notebook = await createMarkdownNotebook(context, params.title, params.markdown)
    return await withPostHogUrl(context, notebook, `/notebooks/${notebook.short_id}`)
}

const tool = (): ToolBase<typeof NotebooksCreateSchema, CreateNotebookResult> => ({
    name: 'notebooks-create',
    schema: NotebooksCreateSchema,
    handler: createNotebookHandler,
})

export default tool
