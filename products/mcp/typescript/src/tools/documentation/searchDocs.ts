import { docsSearch } from '@/inkeepApi'
import { DocumentationSearchSchema } from '@/schema/tool-inputs'
import type { Context, ToolBase } from '@/tools/types'
import type { z } from 'zod'

const schema = DocumentationSearchSchema

type Params = z.infer<typeof schema>

export const searchDocsHandler = async (context: Context, params: Params) => {
    const { query } = params
    const inkeepApiKey = context.env.INKEEP_API_KEY

    if (!inkeepApiKey) {
        return {
            content: [
                {
                    type: 'text',
                    text: 'Error: INKEEP_API_KEY is not configured.',
                },
            ],
        }
    }
    const resultText = await docsSearch(inkeepApiKey, query)
    return { content: [{ type: 'text', text: resultText }] }
}

const tool = (): ToolBase<typeof schema> => ({
    name: 'docs-search',
    schema,
    handler: searchDocsHandler,
})

export default tool
