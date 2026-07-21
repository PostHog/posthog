import { z } from 'zod'

import type { ToolBase } from '@/tools/types'

// Imported at build time so this stays the single source of truth with the Python
// MaxTool, which reads the same file. Too big (~14KB) to embed in a tool description.
import parserRecipeExamples from 'products/ai_observability/backend/prompts/parser_recipe_examples.yaml?raw'

const schema = z.object({})

interface ParserRecipeReferenceResult {
    reference: string
}

export const parserRecipeReferenceHandler: ToolBase<
    typeof schema,
    ParserRecipeReferenceResult
>['handler'] = async () => ({ reference: parserRecipeExamples })

const tool = (): ToolBase<typeof schema, ParserRecipeReferenceResult> => ({
    name: 'llma-parser-recipe-reference',
    schema,
    handler: parserRecipeReferenceHandler,
})

export default tool
