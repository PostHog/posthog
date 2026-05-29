import { isDeepStrictEqual } from 'node:util'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import type { Context, ToolBase } from '@/tools/types'

import editNotebook, { NotebookEditSchema, type ProseMirrorNode } from './edit'

const Subtree = z.union([z.record(z.string(), z.unknown()), z.array(z.unknown())])

const SubtreeReplacementSchema = z
    .object({
        short_id: z.string().describe('The notebook short_id (the public id in the URL, e.g. `aBcD1234`).'),
        old_value: Subtree.describe('The piece of content to find, copied from `notebooks-retrieve`.'),
        new_value: Subtree.describe('The replacement JSON subtree.'),
        replace_all: z.boolean().optional().describe('Replace every place `old_value` matches. Default false.'),
    })
    .refine((v) => !isDeepStrictEqual(v.old_value, v.new_value), {
        message: 'old_value and new_value must differ',
        path: ['new_value'],
    })

export const NotebookEditCombinedSchema = z.union([NotebookEditSchema, SubtreeReplacementSchema])

type Params = z.infer<typeof NotebookEditCombinedSchema>
type SubtreeReplacementParams = z.infer<typeof SubtreeReplacementSchema>

function isSubtreeReplacementParams(params: Params): params is SubtreeReplacementParams {
    return 'old_value' in params
}

function subtreeReplacementParamsToEditParams(params: SubtreeReplacementParams): z.infer<typeof NotebookEditSchema> {
    if (
        !Array.isArray(params.old_value) &&
        !Array.isArray(params.new_value) &&
        params.old_value.type === 'text' &&
        params.new_value.type === 'text' &&
        typeof params.old_value.text === 'string' &&
        typeof params.new_value.text === 'string'
    ) {
        return {
            short_id: params.short_id,
            max_retries: 3,
            edits: [
                {
                    type: 'replace_text',
                    find: params.old_value.text,
                    replace: params.new_value.text,
                    all_occurrences: params.replace_all ?? false,
                    occurrence: 1,
                },
            ],
        }
    }

    const oldNode = params.old_value as ProseMirrorNode | ProseMirrorNode[]
    const newNodes = Array.isArray(params.new_value)
        ? (params.new_value as ProseMirrorNode[])
        : ([params.new_value] as ProseMirrorNode[])

    return {
        short_id: params.short_id,
        max_retries: 3,
        edits: [
            {
                type: 'replace_subtree',
                old_node: oldNode,
                new_nodes: newNodes,
                replace_all: params.replace_all ?? false,
            },
        ],
    }
}

export const editHandler: ToolBase<typeof NotebookEditCombinedSchema, Schemas.Notebook>['handler'] = async (
    context: Context,
    params: Params
) => {
    if (!isSubtreeReplacementParams(params)) {
        return await editNotebook().handler(context, params)
    }

    return await editNotebook().handler(context, subtreeReplacementParamsToEditParams(params))
}

const tool = (): ToolBase<typeof NotebookEditCombinedSchema, Schemas.Notebook> => ({
    name: 'notebook-edit',
    schema: NotebookEditCombinedSchema,
    handler: editHandler,
})

export default tool
