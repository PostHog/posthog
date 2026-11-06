// Copied into `shared/` by scripts/copy-instructions.ts before bundling so this stays
// the single source of truth with the Python MaxTool, which reads the same file.
// Too big (~14KB) to embed in a tool description.
import parserRecipeExamples from '@shared/parser_recipe_examples.yaml'
import { z } from 'zod'

import type { ToolBase } from '@/tools/types'

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
