import { combineUrl } from 'kea-router'

import {
    MAX_NOTEBOOK_VARIABLE_LIST_ITEMS,
    MAX_NOTEBOOK_VARIABLE_VALUE_CHARS,
    type NotebookVariable,
    type NotebookVariableValue,
} from 'scenes/notebooks/Notebook/notebookVariables'
import { urls } from 'scenes/urls'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import { isAbsoluteAppDate } from './notebookAppDate'

function isText(value: unknown): value is string {
    return typeof value === 'string' && Array.from(value).length <= MAX_NOTEBOOK_VARIABLE_VALUE_CHARS
}

function validList(value: unknown): boolean {
    if (!Array.isArray(value) || value.length > MAX_NOTEBOOK_VARIABLE_LIST_ITEMS || !value.every(isText)) {
        return false
    }
    return value.reduce((size, item) => size + Array.from(item).length, 0) <= MAX_NOTEBOOK_VARIABLE_VALUE_CHARS
}

const acceptsValue: Record<NotebookVariable['type'], (value: unknown) => boolean> = {
    string: isText,
    list: validList,
    boolean: (value) => typeof value === 'boolean',
    number: (value) => typeof value === 'number' && Number.isFinite(value),
    date: (value) => isText(value) && isAbsoluteAppDate(value),
}

function validValue(type: NotebookVariable['type'], value: unknown): value is NotebookVariableValue {
    return value === null ? type !== 'list' : acceptsValue[type](value)
}

function validSliderValue(block: NotebookAppBlockApi, value: NotebookVariableValue): boolean {
    const min = block.min ?? 0
    const max = block.max ?? 100
    const step = block.step ?? 1
    if (typeof value !== 'number' || value < min || value > max || step <= 0) {
        return false
    }
    const tick = (value - min) / step
    return Math.abs(tick - Math.round(tick)) < 1e-8
}

function allowedByInput(block: NotebookAppBlockApi, value: NotebookVariableValue): boolean {
    if (block.input_kind === 'select') {
        const options = block.options ?? []
        return (Array.isArray(value) ? value : [value]).every((item) => options.includes(String(item)))
    }
    return block.input_kind !== 'slider' || validSliderValue(block, value)
}

export function restoreAppInputs(
    defaults: NotebookVariable[],
    linked: unknown,
    blocks: NotebookAppBlockApi[]
): NotebookVariable[] {
    if (!linked || typeof linked !== 'object' || Array.isArray(linked)) {
        return defaults
    }
    const restored = defaults.map((variable) => {
        const value: unknown = Object.getOwnPropertyDescriptor(linked, variable.name)?.value
        const inputs = blocks.filter((block) => block.kind === 'input' && block.variable === variable.name)
        return validValue(variable.type, value) &&
            (inputs.length === 0 || inputs.some((block) => allowedByInput(block, value)))
            ? { ...variable, value }
            : variable
    })
    const ranges = blocks.filter((block) => block.kind === 'input' && block.input_kind === 'date_range')
    return ranges.length ? restoreOrderedRanges(defaults, restored, ranges) : restored
}

function restoreOrderedRanges(
    defaults: NotebookVariable[],
    restored: NotebookVariable[],
    ranges: NotebookAppBlockApi[]
): NotebookVariable[] {
    const values = new Map(restored.map((variable) => [variable.name, variable]))
    const fallback = new Map(defaults.map((variable) => [variable.name, variable]))
    let changed = true
    while (changed) {
        changed = false
        for (const { variable, end_variable } of ranges) {
            const start = values.get(variable ?? '')?.value
            const end = values.get(end_variable ?? '')?.value
            if (typeof start !== 'string' || typeof end !== 'string' || start.slice(0, 10) <= end.slice(0, 10)) {
                continue
            }
            for (const name of [variable, end_variable]) {
                const original = fallback.get(name ?? '')
                if (original && values.get(original.name) !== original) {
                    values.set(original.name, original)
                    changed = true
                }
            }
        }
    }
    return [...values.values()]
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

export function notebookAppViewLink(
    project: string,
    shortId: string,
    tab: string,
    variables: NotebookVariable[]
): string {
    return urls.absolute(notebookAppViewPath(project, shortId, tab, variables))
}
