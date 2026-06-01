import { isDeepStrictEqual } from 'node:util'
import { z } from 'zod'

import type { Schemas } from '@/api/generated'
import type { Context, ToolBase } from '@/tools/types'

import editNotebook, { NotebookEditSchema as AnchoredNotebookEditSchema, type ProseMirrorNode } from './edit'

const Subtree = z.union([z.record(z.string(), z.unknown()), z.array(z.unknown())])

const SubtreeReplacementSchema = z
    .object({
        short_id: AnchoredNotebookEditSchema.shape.short_id,
        old_value: Subtree.describe('The piece of content to find, copied from `notebooks-retrieve`.'),
        new_value: Subtree.describe('The replacement JSON subtree.'),
        replace_all: z.boolean().optional().describe('Replace every place `old_value` matches. Default false.'),
    })
    .refine((v) => !isDeepStrictEqual(v.old_value, v.new_value), {
        message: 'old_value and new_value must differ',
        path: ['new_value'],
    })

export const NotebookEditCombinedSchema = z
    .object({
        ...AnchoredNotebookEditSchema.shape,
        edits: AnchoredNotebookEditSchema.shape.edits.optional(),
        max_retries: AnchoredNotebookEditSchema.shape.max_retries.optional(),
        old_value: Subtree.optional().describe('The piece of content to find, copied from `notebooks-retrieve`.'),
        new_value: Subtree.optional().describe('The replacement JSON subtree.'),
        replace_all: z.boolean().optional().describe('Replace every place `old_value` matches. Default false.'),
    })
    .superRefine((value, ctx) => {
        const usesSubtreeReplacement =
            value.old_value !== undefined || value.new_value !== undefined || value.replace_all !== undefined
        if (!usesSubtreeReplacement) {
            if (value.edits === undefined) {
                ctx.addIssue({
                    code: 'custom',
                    message: 'edits are required unless old_value/new_value are provided',
                    path: ['edits'],
                })
            }
            return
        }

        if (value.edits !== undefined) {
            ctx.addIssue({
                code: 'custom',
                message: 'Provide either edits or old_value/new_value, not both.',
                path: ['edits'],
            })
        }
        if (value.old_value === undefined) {
            ctx.addIssue({ code: 'custom', message: 'old_value is required', path: ['old_value'] })
        }
        if (value.new_value === undefined) {
            ctx.addIssue({ code: 'custom', message: 'new_value is required', path: ['new_value'] })
        }
        if (
            value.old_value !== undefined &&
            value.new_value !== undefined &&
            isDeepStrictEqual(value.old_value, value.new_value)
        ) {
            ctx.addIssue({ code: 'custom', message: 'old_value and new_value must differ', path: ['new_value'] })
        }
    })
export { NotebookEditCombinedSchema as NotebookEditSchema }

type Params = z.infer<typeof NotebookEditCombinedSchema>
type SubtreeReplacementParams = z.infer<typeof SubtreeReplacementSchema>
type AnchoredNotebookEditParams = z.infer<typeof AnchoredNotebookEditSchema>
type CompatibilityReplaceTextEdit = Extract<AnchoredNotebookEditParams['edits'][number], { type: 'replace_text' }> & {
    legacy_text_node_replacement?: boolean
}

function isSubtreeReplacementParams(params: Params): params is SubtreeReplacementParams {
    return params.old_value !== undefined || params.new_value !== undefined || params.replace_all !== undefined
}

function subtreeReplacementParamsToEditParams(params: SubtreeReplacementParams): AnchoredNotebookEditParams {
    if (
        !Array.isArray(params.old_value) &&
        !Array.isArray(params.new_value) &&
        params.old_value.type === 'text' &&
        params.new_value.type === 'text' &&
        typeof params.old_value.text === 'string' &&
        typeof params.new_value.text === 'string'
    ) {
        const edit: CompatibilityReplaceTextEdit = {
            type: 'replace_text',
            find: params.old_value.text,
            replace: params.new_value.text,
            all_occurrences: params.replace_all ?? false,
            occurrence: 1,
            legacy_text_node_replacement: true,
        }
        return {
            short_id: params.short_id,
            max_retries: 3,
            edits: [edit],
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
        return await editNotebook().handler(context, AnchoredNotebookEditSchema.parse(params))
    }

    return await editNotebook().handler(
        context,
        subtreeReplacementParamsToEditParams(SubtreeReplacementSchema.parse(params))
    )
}

const tool = (): ToolBase<typeof NotebookEditCombinedSchema, Schemas.Notebook> => ({
    name: 'notebook-edit',
    schema: NotebookEditCombinedSchema,
    handler: editHandler,
})

export default tool
