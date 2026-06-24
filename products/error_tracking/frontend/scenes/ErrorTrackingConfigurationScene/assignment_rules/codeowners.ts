import type { RoleType } from '~/types'

export interface CodeownersEntry {
    pattern: string
    owners: string[]
}

export interface OwnerGroup {
    owner: string
    patterns: string[]
}

export interface RoleMatch {
    role: RoleType
    /** Normalized similarity in [0, 1], where 1 is an exact match. */
    score: number
}

export interface OwnerIdentity {
    org: string
    slug: string
}

/**
 * Split an `@org/team` owner token into its org and team slug — the shape a GitHub-team
 * RoleExternalReference is keyed on. Returns null for bare users (`@alice`) and emails, which have
 * no org and so cannot be persisted as a team mapping.
 */
export function splitOwner(owner: string): OwnerIdentity | null {
    const withoutAt = owner.replace(/^@/, '')
    const slashIdx = withoutAt.indexOf('/')
    if (slashIdx < 0) {
        return null
    }
    const org = withoutAt.slice(0, slashIdx).trim()
    const slug = withoutAt.slice(slashIdx + 1).trim()
    return org && slug ? { org, slug } : null
}

/**
 * Parse CODEOWNERS-style text into (pattern, owners) entries. Mirrors the parsing in
 * .github/scripts/codeowners.js: skip blank lines and `#` comments, first token is the path
 * pattern and the rest are owners (`@org/team`, `@user`, or an email).
 */
export function parseCodeowners(text: string): CodeownersEntry[] {
    const entries: CodeownersEntry[] = []
    for (const rawLine of text.split(/\r?\n/)) {
        const line = rawLine.trim()
        if (!line || line.startsWith('#')) {
            continue
        }
        const [pattern, ...owners] = line.split(/\s+/)
        if (!pattern || owners.length === 0) {
            continue
        }
        entries.push({ pattern, owners })
    }
    return entries
}

export interface CodeownersError {
    /** 1-based line number. */
    line: number
    reason: string
}

const OWNER_RE = /^@[A-Za-z0-9/_.-]+$/
const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/

/**
 * Validate CODEOWNERS-style text line by line, returning a parse error per malformed line: a path
 * with no owner, or an owner token that isn't a `@team`/`@user` handle or an email. Blank lines and
 * `#` comments are skipped.
 */
export function findCodeownersErrors(text: string): CodeownersError[] {
    const errors: CodeownersError[] = []
    text.split(/\r?\n/).forEach((rawLine, index) => {
        const line = rawLine.trim()
        if (!line || line.startsWith('#')) {
            return
        }
        const [pattern, ...owners] = line.split(/\s+/)
        if (owners.length === 0) {
            errors.push({ line: index + 1, reason: `"${pattern}" has no owner` })
            return
        }
        const invalid = owners.filter((owner) => !OWNER_RE.test(owner) && !EMAIL_RE.test(owner))
        if (invalid.length > 0) {
            errors.push({ line: index + 1, reason: `invalid owner ${invalid.join(', ')}` })
        }
    })
    return errors
}

/**
 * Collapse entries so each distinct owner appears once, accumulating every path it owns. Owner
 * order follows first appearance; patterns within an owner are de-duplicated and kept in order.
 */
export function groupByOwner(entries: CodeownersEntry[]): OwnerGroup[] {
    const byOwner = new Map<string, string[]>()
    const order: string[] = []
    for (const { pattern, owners } of entries) {
        for (const owner of owners) {
            let patterns = byOwner.get(owner)
            if (!patterns) {
                patterns = []
                byOwner.set(owner, patterns)
                order.push(owner)
            }
            if (!patterns.includes(pattern)) {
                patterns.push(pattern)
            }
        }
    }
    return order.map((owner) => ({ owner, patterns: byOwner.get(owner) ?? [] }))
}

/**
 * Turn a CODEOWNERS glob into a path fragment for an `icontains` match against `$exception_sources`.
 * Stack-frame source paths are often absolute or transformed, so we match a substring rather than
 * trying to honor full glob semantics. Extension-only patterns become their extension (`.py`, `.tsx`).
 * Returns an empty string for catch-all patterns (e.g. `*`), which callers should skip.
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

/**
 * The de-duplicated, non-empty `icontains` path fragments an owner's patterns reduce to — i.e. the
 * exact substrings a generated rule matches against `$exception_sources`. Surfaced in the UI so the
 * user can see what each rule will actually match on.
 */
export function ownerMatchFragments(patterns: string[]): string[] {
    return Array.from(new Set(patterns.map(patternToSourceValue))).filter((value) => value.length > 0)
}

function normalizeName(value: string): string {
    return value.toLowerCase().replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim()
}

/** Normalize an owner token to a comparable team name: drop `@`, keep the segment after `/`. */
function normalizeOwnerToken(owner: string): string {
    const withoutAt = owner.replace(/^@/, '')
    const lastSlash = withoutAt.lastIndexOf('/')
    return normalizeName(lastSlash >= 0 ? withoutAt.slice(lastSlash + 1) : withoutAt)
}

/** Standard iterative Levenshtein edit distance between two strings. */
export function levenshtein(a: string, b: string): number {
    if (a.length === 0) {
        return b.length
    }
    if (b.length === 0) {
        return a.length
    }
    let prev = Array.from({ length: b.length + 1 }, (_, i) => i)
    let curr = Array.from({ length: b.length + 1 }, () => 0)
    for (let i = 1; i <= a.length; i++) {
        curr[0] = i
        for (let j = 1; j <= b.length; j++) {
            const cost = a[i - 1] === b[j - 1] ? 0 : 1
            curr[j] = Math.min(prev[j] + 1, curr[j - 1] + 1, prev[j - 1] + cost)
        }
        ;[prev, curr] = [curr, prev]
    }
    return prev[b.length]
}

/**
 * Find the existing Role whose name is closest to a CODEOWNERS owner token by normalized
 * Levenshtein similarity. Returns null when no role clears `threshold` (default 0.5).
 */
export function bestRoleMatch(owner: string, roles: RoleType[], threshold: number = 0.5): RoleMatch | null {
    const target = normalizeOwnerToken(owner)
    if (!target || roles.length === 0) {
        return null
    }
    let best: RoleMatch | null = null
    for (const role of roles) {
        const name = normalizeName(role.name)
        const distance = levenshtein(target, name)
        const score = 1 - distance / Math.max(target.length, name.length, 1)
        if (!best || score > best.score) {
            best = { role, score }
        }
    }
    return best && best.score >= threshold ? best : null
}
