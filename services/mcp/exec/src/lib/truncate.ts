export interface CapResult {
    display: string
    truncated: boolean
    shapeHint?: string
}

export function capJson(value: unknown, maxBytes: number): CapResult {
    let serialized: string
    try {
        serialized = JSON.stringify(value)
    } catch {
        return { display: '<unserializable>', truncated: true, shapeHint: shapeOf(value) }
    }
    if (serialized === undefined) {
        return { display: 'undefined', truncated: false }
    }
    const byteLen = Buffer.byteLength(serialized, 'utf8')
    if (byteLen <= maxBytes) {
        return { display: serialized, truncated: false }
    }
    return {
        display: serialized.slice(0, maxBytes) + '…',
        truncated: true,
        shapeHint: shapeOf(value),
    }
}

export function shapeOf(value: unknown, depth = 0): string {
    if (value === null) {
        return 'null'
    }
    if (Array.isArray(value)) {
        if (depth > 1 || value.length === 0) {
            return `array[${value.length}]`
        }
        return `array[${value.length}]<${shapeOf(value[0], depth + 1)}>`
    }
    if (typeof value === 'object') {
        const keys = Object.keys(value as Record<string, unknown>)
            .sort()
            .slice(0, 12)
        const more = Object.keys(value as Record<string, unknown>).length - keys.length
        const summary = keys.join(', ') + (more > 0 ? `, +${more} more` : '')
        return `object{${summary}}`
    }
    return `typeof:${typeof value}`
}
