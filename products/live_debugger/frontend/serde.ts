interface ParsedVariable {
    type: 'simple' | 'complex'
    value: any
    typeName?: string
}

/**
 * Parse and clean jsonpickle serialized variables.
 * Returns an object with type ('simple' or 'complex'), the cleaned value, and optional type name.
 */
export function parseJsonPickleVariable(value: any): ParsedVariable {
    // If it's already not a string, return as-is
    if (typeof value !== 'string') {
        return { type: typeof value === 'object' && value !== null ? 'complex' : 'simple', value }
    }

    try {
        const parsed = JSON.parse(value)

        // Simple types: null, boolean, number, or plain string
        if (parsed === null || typeof parsed === 'boolean' || typeof parsed === 'number') {
            return { type: 'simple', value: parsed }
        }

        if (typeof parsed === 'string') {
            return { type: 'simple', value: parsed }
        }

        // Complex types: objects and arrays
        if (typeof parsed === 'object') {
            // Extract type name from py/object if present
            const typeName = parsed['py/object'] ? String(parsed['py/object']) : undefined

            // Clean jsonpickle metadata (keys starting with 'py/')
            const cleaned = cleanJsonPickleMetadata(parsed)
            return { type: 'complex', value: cleaned, typeName }
        }

        return { type: 'simple', value: parsed }
    } catch {
        // If parsing fails, treat as simple string
        return { type: 'simple', value }
    }
}

/**
 * Recursively remove jsonpickle metadata keys (py/*) from objects
 */
function cleanJsonPickleMetadata(obj: any): any {
    if (obj === null || typeof obj !== 'object') {
        return obj
    }

    if (Array.isArray(obj)) {
        return obj.map(cleanJsonPickleMetadata)
    }

    const cleaned: Record<string, any> = {}
    for (const [key, value] of Object.entries(obj)) {
        // Skip jsonpickle metadata keys
        if (key.startsWith('py/')) {
            continue
        }
        cleaned[key] = cleanJsonPickleMetadata(value)
    }

    return cleaned
}
