import api from 'lib/api'
import { convertHogToJS, execHog } from 'lib/hog'

import type { WidgetFrameApi } from 'products/notebooks/frontend/generated/api.schemas'

export type ReusableWidgetInputBinding = {
    source: string
    hog?: string
    bytecode?: unknown[]
}

function frameRowsAsObjects(frame: WidgetFrameApi): Record<string, unknown>[] {
    return frame.rows.map((row) =>
        Object.fromEntries(frame.columns.map((column, index) => [column.name, row[index] ?? null]))
    )
}

const compiledBindings = new Map<string, Promise<unknown[]>>()

async function bindingBytecode(binding: ReusableWidgetInputBinding): Promise<unknown[] | undefined> {
    if (binding.bytecode) {
        return binding.bytecode
    }
    if (!binding.hog?.trim()) {
        return undefined
    }
    let compiled = compiledBindings.get(binding.hog)
    if (!compiled) {
        compiled = api.hog.create(binding.hog).then((response) => response.bytecode as unknown[])
        compiledBindings.set(binding.hog, compiled)
    }
    return await compiled
}

export async function applyReusableWidgetBinding(
    frame: WidgetFrameApi,
    logicalName: string,
    binding: ReusableWidgetInputBinding | undefined,
    expectedColumns: string[] = []
): Promise<WidgetFrameApi> {
    if (!binding) {
        return { ...frame, name: logicalName }
    }
    const bytecode = await bindingBytecode(binding)
    if (!bytecode) {
        return { ...frame, name: logicalName }
    }
    if (!Array.isArray(bytecode) || bytecode[0] !== '_H') {
        throw new Error(`The input mapping for "${logicalName}" has invalid compiled Hog code.`)
    }
    const sourceRows = frameRowsAsObjects(frame)
    const execution = execHog(bytecode, {
        globals: {
            columns: frame.columns,
            frame: { ...frame, rows: sourceRows },
            rows: sourceRows,
        },
        functions: {},
        maxAsyncSteps: 0,
        memoryLimit: 16 * 1024 * 1024,
        timeout: 100,
    })
    if (execution.error || !execution.finished) {
        throw new Error(`The input mapping for "${logicalName}" could not be evaluated.`)
    }
    const mapped = convertHogToJS(execution.result)
    if (!Array.isArray(mapped) || mapped.some((row) => !row || typeof row !== 'object' || Array.isArray(row))) {
        throw new Error(`The input mapping for "${logicalName}" must return a list of objects.`)
    }
    const records = mapped as Record<string, unknown>[]
    const columnNames = Array.from(new Set(records.flatMap((row) => Object.keys(row)))).slice(0, 100)
    const missingColumns = expectedColumns.filter((name) => !columnNames.includes(name))
    if (records.length && missingColumns.length) {
        throw new Error(
            `The input mapping for "${logicalName}" must return the contract column "${missingColumns[0]}".`
        )
    }
    return {
        ...frame,
        name: logicalName,
        columns: columnNames.map((name) => ({ name, type: 'unknown' })),
        rows: records.map((row) => columnNames.map((name) => row[name] ?? null)),
        includedRowCount: records.length,
    }
}

export function getReusableWidgetInputBinding(
    inputBindings: Record<string, unknown>,
    logicalName: string
): ReusableWidgetInputBinding | undefined {
    const binding = inputBindings[logicalName]
    if (!binding || typeof binding !== 'object' || Array.isArray(binding)) {
        return undefined
    }
    const value = binding as Record<string, unknown>
    if (typeof value.source !== 'string') {
        return undefined
    }
    return {
        source: value.source,
        hog: typeof value.hog === 'string' ? value.hog : undefined,
        bytecode: Array.isArray(value.bytecode) ? value.bytecode : undefined,
    }
}
