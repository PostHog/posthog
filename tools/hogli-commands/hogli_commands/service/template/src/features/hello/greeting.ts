export function greetingFor(name: string): string | null {
    const normalizedName = name.trim()
    if (!normalizedName || normalizedName.length > 64) {
        return null
    }
    return `Hello, ${normalizedName}.`
}
