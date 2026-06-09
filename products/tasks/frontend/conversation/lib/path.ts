/**
 * Small path helpers vendored from apps/code/src/renderer/utils/path.ts.
 * Used by prompt-content extraction and tool renderers.
 */

export function getFileName(filePath: string): string {
    const parts = filePath.split(/[\\/]/)
    return parts[parts.length - 1] || filePath
}

export function getFileExtension(filePath: string): string {
    const name = getFileName(filePath)
    const lastDot = name.lastIndexOf('.')
    return lastDot >= 0 ? name.slice(lastDot + 1).toLowerCase() : ''
}

/** Collapse `/Users/<name>` and `/home/<name>` prefixes to `~`. */
export function compactHomePath(text: string): string {
    if (typeof text !== 'string') {
        return String(text)
    }
    return text.replace(/\/Users\/[^/\s]+/g, '~').replace(/\/home\/[^/\s]+/g, '~')
}
