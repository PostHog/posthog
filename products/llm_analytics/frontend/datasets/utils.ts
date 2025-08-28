export const EMPTY_JSON = '{\n  \n}'

/**
 * Coerce a string to a valid JSON object or null.
 * @param maybeJson - The string to coerce
 * @returns The coerced JSON object or null
 */
export function corseJsonToObject(maybeJson: string | null): Record<string, any> | null {
    if (!maybeJson) {
        return null
    }
    try {
        const parsedObject = JSON.parse(maybeJson)
        // Regular object or null
        if (typeof parsedObject === 'object') {
            return parsedObject as Record<string, any>
        }
        return null
    } catch {
        return null
    }
}

/**
 * Check if the metadata is a valid JSON object or is an empty string.
 * @param metadata - The metadata to check
 * @returns True if the metadata is valid, false otherwise
 */
export function isStringJsonObject(maybeJson: string | null): boolean {
    if (!maybeJson) {
        return true
    }
    try {
        const parsedObject = JSON.parse(maybeJson)
        if (typeof parsedObject !== 'object' || parsedObject === null) {
            return false
        }
    } catch {
        return false
    }
    return true
}
