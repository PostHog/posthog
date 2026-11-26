import { combineUrl } from 'kea-router'

import {
    MAX_NOTEBOOK_VARIABLE_LIST_ITEMS,
    MAX_NOTEBOOK_VARIABLE_VALUE_CHARS,
    type NotebookVariable,
    type NotebookVariableValue,
} from 'scenes/notebooks/Notebook/notebookVariables'
import { urls } from 'scenes/urls'

function isText(value: unknown): value is string {
    return typeof value === 'string' && value.length <= MAX_NOTEBOOK_VARIABLE_VALUE_CHARS
}

const acceptsValue: Record<NotebookVariable['type'], (value: unknown) => boolean> = {
    string: isText,
    list: (value) => Array.isArray(value) && value.length <= MAX_NOTEBOOK_VARIABLE_LIST_ITEMS && value.every(isText),
    boolean: (value) => typeof value === 'boolean',
    number: (value) => typeof value === 'number' && Number.isFinite(value),
    date: (value) => isText(value) && /^\d{4}-\d{2}-\d{2}(?:$|T)/.test(value) && Number.isFinite(Date.parse(value)),
}

function validValue(type: NotebookVariable['type'], value: unknown): value is NotebookVariableValue {
    return value === null ? type !== 'list' : acceptsValue[type](value)
}

export function restoreAppInputs(defaults: NotebookVariable[], linked: unknown): NotebookVariable[] {
    if (!linked || typeof linked !== 'object' || Array.isArray(linked)) {
        return defaults
    }
    return defaults.map((variable) => {
        const value: unknown = Object.getOwnPropertyDescriptor(linked, variable.name)?.value
        return validValue(variable.type, value) ? { ...variable, value } : variable
    })
}

export function notebookAppViewPath(
    project: string,
    shortId: string,
    tab: string,
    variables: NotebookVariable[]
): string {
    const inputs = Object.fromEntries(variables.map(({ name, value }) => [name, value]))
    return combineUrl(urls.project(project, urls.notebook(shortId)), { view: 'app' }, { appView: { tab, inputs } }).url
}
