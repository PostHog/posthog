import { combineUrl } from 'kea-router'

import {
    MAX_NOTEBOOK_VARIABLE_LIST_ITEMS,
    MAX_NOTEBOOK_VARIABLE_VALUE_CHARS,
    type NotebookVariable,
    type NotebookVariableValue,
} from 'scenes/notebooks/Notebook/notebookVariables'
import { urls } from 'scenes/urls'

import type { NotebookAppBlockApi } from '../generated/api.schemas'

function isText(value: unknown): value is string {
    return typeof value === 'string' && Array.from(value).length <= MAX_NOTEBOOK_VARIABLE_VALUE_CHARS
}

function validList(value: unknown): boolean {
    if (!Array.isArray(value) || value.length > MAX_NOTEBOOK_VARIABLE_LIST_ITEMS || !value.every(isText)) {
        return false
    }
    return value.reduce((size, item) => size + Array.from(item).length, 0) <= MAX_NOTEBOOK_VARIABLE_VALUE_CHARS
}

function validDate(value: unknown): boolean {
    if (!isText(value)) {
        return false
    }
    const match =
        /^(\d{4})-(\d{2})-(\d{2})(?:[T ](?:[01]\d|2[0-3])(?::?[0-5]\d(?::?[0-5]\d(?:[.,]\d+)?)?)?(?:Z|[+-](?:[01]\d|2[0-3])(?::?[0-5]\d)?)?)?$/.exec(
            value.trim()
        )
    if (!match) {
        return false
    }
    const [, year, month, day] = match
    const calendar = new Date(0)
    calendar.setUTCFullYear(Number(year), Number(month) - 1, Number(day))
    return Number(year) > 0 && calendar.getUTCMonth() === Number(month) - 1 && calendar.getUTCDate() === Number(day)
}

const acceptsValue: Record<NotebookVariable['type'], (value: unknown) => boolean> = {
    string: isText,
    list: validList,
    boolean: (value) => typeof value === 'boolean',
    number: (value) => typeof value === 'number' && Number.isFinite(value),
    date: validDate,
}

function validValue(type: NotebookVariable['type'], value: unknown): value is NotebookVariableValue {
    return value === null ? type !== 'list' : acceptsValue[type](value)
}

function allowedByInput(block: NotebookAppBlockApi, value: NotebookVariableValue): boolean {
    if (block.input_kind === 'select') {
        const options = block.options ?? []
        return (Array.isArray(value) ? value : [value]).every((item) => options.includes(String(item)))
    }
    if (block.input_kind === 'slider') {
        const min = block.min ?? 0
        const max = block.max ?? 100
        const step = block.step ?? 1
        if (typeof value !== 'number' || value < min || value > max || step <= 0) {
            return false
        }
        const tick = (value - min) / step
        return Math.abs(tick - Math.round(tick)) < 1e-8
    }
    return true
}

export function restoreAppInputs(
    defaults: NotebookVariable[],
    linked: unknown,
    blocks: NotebookAppBlockApi[]
): NotebookVariable[] {
    if (!linked || typeof linked !== 'object' || Array.isArray(linked)) {
        return defaults
    }
    return defaults.map((variable) => {
        const value: unknown = Object.getOwnPropertyDescriptor(linked, variable.name)?.value
        const inputs = blocks.filter((block) => block.kind === 'input' && block.variable === variable.name)
        return validValue(variable.type, value) &&
            (inputs.length === 0 || inputs.some((block) => allowedByInput(block, value)))
            ? { ...variable, value }
            : variable
    })
}

export function notebookAppViewLink(
    project: string,
    shortId: string,
    tab: string,
    variables: NotebookVariable[]
): string {
    const inputs = Object.fromEntries(variables.map(({ name, value }) => [name, value]))
    return urls.absolute(
        combineUrl(urls.project(project, urls.notebook(shortId)), { view: 'app' }, { appView: { tab, inputs } }).url
    )
}
