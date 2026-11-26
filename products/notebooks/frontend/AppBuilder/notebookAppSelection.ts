import { retryImport } from 'lib/utils/retryImport'
import {
    coerceNotebookVariableValue,
    type NotebookVariable,
    type NotebookVariableValue,
} from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppBlockApi } from '../generated/api.schemas'

export async function resolveAppSelection(
    selection: NonNullable<NotebookAppBlockApi['selection']>,
    row: Record<string, unknown>,
    variables: NotebookVariable[]
): Promise<{ name: string; value: NotebookVariableValue } | null> {
    const target = variables.find((variable) => variable.name === selection.variable)
    if (!target || !Object.hasOwn(row, selection.column)) {
        return null
    }
    const value = row[selection.column]
    if (typeof value !== 'string' && typeof value !== 'number' && typeof value !== 'boolean') {
        return null
    }
    if (selection.condition) {
        const code = selection.condition_bytecode
        if (!Array.isArray(code) || code[0] !== '_H') {
            throw new Error('Save the selection condition before trying it.')
        }
        const { execHog } = await retryImport(() => import('lib/hog'))
        const result = execHog(code, {
            globals: { row, value, inputs: Object.fromEntries(variables.map((input) => [input.name, input.value])) },
            functions: {},
            maxAsyncSteps: 0,
            memoryLimit: 1024 * 1024,
            timeout: 20,
        })
        if (result.error || !result.finished || typeof result.result !== 'boolean') {
            throw new Error('The selection condition must return true or false.')
        }
        if (!result.result) {
            return null
        }
    }
    const next = coerceNotebookVariableValue(target.type, target.type === 'list' ? [String(value)] : value)
    return next === null ? null : { name: target.name, value: next }
}
