const GENERATED_NAME_MAX_LENGTH = 80

export function getWidgetName(prompt: string): string {
    const normalized = prompt.trim().replace(/\s+/g, ' ')
    if (!normalized) {
        return 'Generated widget'
    }
    if (normalized.length <= GENERATED_NAME_MAX_LENGTH) {
        return normalized
    }
    return `${normalized.slice(0, GENERATED_NAME_MAX_LENGTH - 3).trimEnd()}...`
}
