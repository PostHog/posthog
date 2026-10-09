// The builder matches a regex anywhere in the value (ClickHouse `match`), PromQL anchors it at both
// ends. These two functions translate between the two, so that a builder regex survives a round trip
// through PromQL as the same string.

const hasTopLevelAlternation = (pattern: string): boolean => {
    let depth = 0
    let inClass = false
    for (let i = 0; i < pattern.length; i++) {
        const ch = pattern[i]
        if (ch === '\\') {
            i++
        } else if (inClass) {
            inClass = ch !== ']'
        } else if (ch === '[') {
            inClass = true
        } else if (ch === '(') {
            depth++
        } else if (ch === ')') {
            depth--
        } else if (ch === '|' && depth === 0) {
            return true
        }
    }
    return false
}

/** `(?:X)` → `X` when the group spans the whole pattern. */
const unwrapGroup = (pattern: string): string => {
    if (!pattern.startsWith('(?:') || !pattern.endsWith(')')) {
        return pattern
    }
    let depth = 0
    for (let i = 0; i < pattern.length; i++) {
        const ch = pattern[i]
        if (ch === '\\') {
            i++
        } else if (ch === '(') {
            depth++
        } else if (ch === ')') {
            depth--
            if (depth === 0 && i !== pattern.length - 1) {
                return pattern
            }
        }
    }
    return pattern.slice(3, -1)
}

const group = (pattern: string): string => (hasTopLevelAlternation(pattern) ? `(?:${pattern})` : pattern)

const endsWithUnescaped = (pattern: string, suffix: string): boolean => {
    if (!pattern.endsWith(suffix)) {
        return false
    }
    let backslashes = 0
    for (let i = pattern.length - suffix.length - 1; i >= 0 && pattern[i] === '\\'; i--) {
        backslashes++
    }
    return backslashes % 2 === 0
}

export function builderRegexToPromRegex(pattern: string): string {
    const anchoredStart = pattern.startsWith('^')
    const anchoredEnd = endsWithUnescaped(pattern, '$') && pattern.length > (anchoredStart ? 1 : 0)
    const core = pattern.slice(anchoredStart ? 1 : 0, anchoredEnd ? -1 : undefined)
    if (anchoredStart && anchoredEnd) {
        return unwrapGroup(core)
    }
    return `${anchoredStart ? '' : '.*'}${group(core)}${anchoredEnd ? '' : '.*'}`
}

export function promRegexToBuilderRegex(pattern: string): string {
    const openStart = pattern.startsWith('.*')
    const rest = openStart ? pattern.slice(2) : pattern
    const openEnd = rest.length >= 2 && endsWithUnescaped(rest, '.*')
    let core = openEnd ? rest.slice(0, -2) : rest
    if (openStart && openEnd) {
        return unwrapGroup(core)
    }
    if (hasTopLevelAlternation(core)) {
        core = `(?:${core})`
    }
    return `${openStart ? '' : '^'}${core}${openEnd ? '' : '$'}`
}
