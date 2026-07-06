import type { OrganizationMemberType, RoleType } from '~/types'

export type AssigneeMatch =
    | { type: 'role'; role: RoleType; score: number }
    | { type: 'user'; user: OrganizationMemberType['user']; score: number }

const MIN_FUZZY_OWNER_LENGTH = 5

function normalizeName(value: string): string {
    return value.toLowerCase().replace(/[-_]+/g, ' ').replace(/\s+/g, ' ').trim()
}

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
    return longestCommonSubstringLength(target, candidate) / Math.max(Math.min(target.length, candidate.length), 1)
}

function scoreCandidate(target: string, candidate: string): number {
    const normalizedCandidate = normalizeName(candidate)
    if (target.length < MIN_FUZZY_OWNER_LENGTH && target !== normalizedCandidate) {
        return 0
    }
    return commonSubstringScore(target, normalizedCandidate)
}

function userNames(member: OrganizationMemberType): string[] {
    const { user } = member
    return [user.first_name, user.email.split('@')[0], user.email]
        .map((value) => normalizeName(value))
        .filter((value) => value.length > 0)
}

function roleMatch(target: string, role: RoleType): AssigneeMatch {
    return { type: 'role', role, score: scoreCandidate(target, role.name) }
}

function userMatch(target: string, member: OrganizationMemberType): AssigneeMatch {
    const score = Math.max(...userNames(member).map((name) => scoreCandidate(target, name)), 0)
    return { type: 'user', user: member.user, score }
}

export function bestAssigneeMatch(
    owner: string,
    roles: RoleType[],
    members: OrganizationMemberType[],
    threshold: number = 0.75
): AssigneeMatch | null {
    const target = normalizeOwnerToken(owner)
    const matches = [
        ...roles.map((role) => roleMatch(target, role)),
        ...members.map((member) => userMatch(target, member)),
    ]
    const best = matches.reduce<AssigneeMatch | null>(
        (best, match) => (!best || match.score > best.score ? match : best),
        null
    )
    const requiredScore = target.length < MIN_FUZZY_OWNER_LENGTH ? 1 : threshold
    return best && best.score >= requiredScore ? best : null
}
