import type { OrganizationMemberType, RoleType } from '~/types'

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

export type AssigneeMatch =
    | { type: 'role'; role: RoleType; score: number }
    | { type: 'user'; user: OrganizationMemberType['user']; score: number }

export interface OwnerIdentity {
    org: string
    slug: string
}

export interface SourceMatch {
    operator: 'icontains' | 'regex'
    value: string
}

/**
 * Split an `@org/team` owner token into its org and team slug. Returns null for bare users
 * (`@alice`) and emails, which do not identify a team.
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
 * Parse code owners-style text into (pattern, owners) entries: skip blank lines and `#` comments,
 * first token is the path pattern and the rest are owners (`@org/team`, `@user`, or an email).
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
 * Validate code owners-style text line by line, returning a parse error per malformed line: a path
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
 * Turn a code owners glob into a path fragment for an `icontains` match against `$exception_sources`.
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
    if (!value) {
        return null
    }
    return { operator: isGlobPattern(pattern) ? 'regex' : 'icontains', value }
}

/**
 * The de-duplicated, non-empty `icontains` path fragments an owner's patterns reduce to — i.e. the
 * exact substrings a generated rule matches against `$exception_sources`. Surfaced in the UI so the
 * user can see what each rule will actually match on.
 */
export function ownerMatchFragments(patterns: string[]): string[] {
    return Array.from(new Set(patterns.map((pattern) => patternToSourceMatch(pattern)?.value ?? ''))).filter(
        (value) => value.length > 0
    )
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

export function longestCommonSubstringLength(a: string, b: string): number {
    if (!a || !b) {
        return 0
    }

    let best = 0
    let previous = Array.from({ length: b.length + 1 }, () => 0)
    let current = Array.from({ length: b.length + 1 }, () => 0)

    for (let i = 1; i <= a.length; i++) {
        for (let j = 1; j <= b.length; j++) {
            current[j] = a[i - 1] === b[j - 1] ? previous[j - 1] + 1 : 0
            best = Math.max(best, current[j])
        }
        ;[previous, current] = [current, previous]
        current.fill(0)
    }

    return best
}

function commonSubstringScore(target: string, candidate: string): number {
    const commonLength = longestCommonSubstringLength(target, candidate)
    return commonLength / Math.max(Math.min(target.length, candidate.length), 1)
}

function userNames(member: OrganizationMemberType): string[] {
    const { user } = member
    return [user.first_name, user.email.split('@')[0], user.email]
        .map((value) => normalizeName(value))
        .filter((value) => value.length > 0)
}

/**
 * Find the existing role or user whose name has the longest normalized common substring with a
 * code owner token. Returns null when no assignee clears `threshold` (default 0.75).
 */
export function bestAssigneeMatch(
    owner: string,
    roles: RoleType[],
    members: OrganizationMemberType[],
    threshold: number = 0.75
): AssigneeMatch | null {
    const target = normalizeOwnerToken(owner)
    if (!target || (roles.length === 0 && members.length === 0)) {
        return null
    }

    let best: AssigneeMatch | null = null
    for (const role of roles) {
        const score = commonSubstringScore(target, normalizeName(role.name))
        if (!best || score > best.score) {
            best = { type: 'role', role, score }
        }
    }
    for (const member of members) {
        const score = Math.max(...userNames(member).map((name) => commonSubstringScore(target, name)), 0)
        if (!best || score > best.score) {
            best = { type: 'user', user: member.user, score }
        }
    }

    return best && best.score >= threshold ? best : null
}

export function bestRoleMatch(owner: string, roles: RoleType[], threshold: number = 0.75): RoleMatch | null {
    const match = bestAssigneeMatch(owner, roles, [], threshold)
    return match?.type === 'role' ? { role: match.role, score: match.score } : null
}
