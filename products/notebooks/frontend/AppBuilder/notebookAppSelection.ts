import { retryImport } from 'lib/utils/retryImport'
import {
    MAX_NOTEBOOK_VARIABLE_VALUE_CHARS,
    coerceNotebookVariableValue,
    type NotebookVariable,
    type NotebookVariableValue,
} from 'scenes/notebooks/Notebook/notebookVariables'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import { isAbsoluteAppDate } from './notebookAppDate'

type Selection = NonNullable<NotebookAppBlockApi['selection']>
type SelectedValue = string | number | boolean

async function matchesCondition(
    selection: Selection,
    row: Record<string, unknown>,
    value: SelectedValue,
    variables: NotebookVariable[]
): Promise<boolean> {
    if (!selection.condition) {
        return true
    }
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
    return result.result
}

function inputValue(type: NotebookVariable['type'], value: SelectedValue): NotebookVariableValue {
    const text = String(value)
    if (Array.from(text).length > MAX_NOTEBOOK_VARIABLE_VALUE_CHARS) {
        return null
    }
    switch (type) {
        case 'boolean':
            return /^(true|false)$/i.test(text.trim()) ? text.trim().toLowerCase() === 'true' : null
        case 'number':
            return text.trim() === '' ? null : coerceNotebookVariableValue('number', value)
        case 'date':
            return isAbsoluteAppDate(text) ? text : null
        case 'list':
            return [text]
        case 'string':
            return text
    }
}

export async function resolveAppSelection(
    selection: Selection,
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
    if (!(await matchesCondition(selection, row, value, variables))) {
        return null
    }
    const next = inputValue(target.type, value)
    return next === null ? null : { name: target.name, value: next }
}
