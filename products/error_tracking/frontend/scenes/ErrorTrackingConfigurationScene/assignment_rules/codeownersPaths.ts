export interface SourceMatch {
    operator: 'icontains' | 'regex'
    value: string
}

/**
 * Turn a code owners glob into a path fragment for an `icontains` match against `$exception_sources`.
 * Stack-frame source paths are often absolute or transformed, so we match a substring rather than
 * trying to honor full glob semantics. Extension-only patterns become their extension (`.py`, `.tsx`).
 */
export function patternToSourceValue(pattern: string): string {
    const trimmed = pattern.trim().replace(/^\/+/, '')
    const extMatch = trimmed.match(/(?:^|\/)\*+(\.[A-Za-z0-9.]+)$/)
    if (extMatch) {
        return extMatch[1]
    }
    return trimmed
        .replace(/\*+/g, '')
        .replace(/\/{2,}/g, '/')
        .replace(/^\/+|\/+$/g, '')
}

function escapeRegex(value: string): string {
    return value.replace(/[|\\{}()[\]^$+?.]/g, '\\$&')
}

export function isGlobPattern(pattern: string): boolean {
    return /[*?[]/.test(pattern)
}

export function globPatternToRegex(pattern: string): string {
    const trimmed = pattern.trim().replace(/^\/+/, '')
    if (!trimmed || /^\*+$/.test(trimmed)) {
        return ''
    }

    let regex = '(^|/)'
    for (let i = 0; i < trimmed.length; i++) {
        const char = trimmed[i]
        const nextChar = trimmed[i + 1]
        if (char === '*' && nextChar === '*') {
            regex += '.*'
            i++
        } else if (char === '*') {
            regex += '[^/]*'
        } else if (char === '?') {
            regex += '[^/]'
        } else {
            regex += escapeRegex(char)
        }
    }
    return regex
}

export function patternToSourceMatch(pattern: string): SourceMatch | null {
    const value = isGlobPattern(pattern) ? globPatternToRegex(pattern) : patternToSourceValue(pattern)
    return value ? { operator: isGlobPattern(pattern) ? 'regex' : 'icontains', value } : null
}

export function ownerMatchFragments(patterns: string[]): string[] {
    return Array.from(new Set(patterns.map((pattern) => patternToSourceMatch(pattern)?.value ?? ''))).filter(Boolean)
}
