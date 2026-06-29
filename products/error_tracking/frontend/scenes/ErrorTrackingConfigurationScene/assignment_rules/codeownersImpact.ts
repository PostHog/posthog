import { Assignee } from '../../../components/Assignee/assigneeSelectLogic'
import { CodeOwnerRuleCandidate } from './codeownersImport'
import { MatchCount } from './codeOwnersModalLogic'

export interface CodeOwnersImpactRow {
    key: string
    label: string
    exceptionCount: number
    issueCount: number
    patterns: string[]
}

function assigneeKey(assignee: NonNullable<CodeOwnerRuleCandidate['assignee']>): string {
    return assignee.type === 'role' ? `role:${assignee.id}` : `user:${assignee.id}`
}

function assigneeLabel(assignee: Assignee): string {
    if (!assignee) {
        return 'Assign…'
    }
    return assignee.type === 'role' ? assignee.role.name : assignee.user.first_name || assignee.user.email
}

export function buildImpactRows(
    savableRows: CodeOwnerRuleCandidate[],
    matchResults: Record<string, MatchCount | null>,
    resolveAssignee: (assignee: CodeOwnerRuleCandidate['assignee']) => Assignee
): CodeOwnersImpactRow[] {
    const groups = new Map<string, CodeOwnersImpactRow>()

    for (const row of savableRows) {
        if (!row.assignee) {
            continue
        }

        const resolved = resolveAssignee(row.assignee)
        if (!resolved) {
            continue
        }

        const key = assigneeKey(row.assignee)
        const existing = groups.get(key) ?? {
            key,
            label: assigneeLabel(resolved),
            exceptionCount: 0,
            issueCount: 0,
            patterns: [],
        }
        const count = matchResults[row.entryId]
        existing.exceptionCount += count?.exceptionCount ?? 0
        existing.issueCount += count?.issueCount ?? 0
        existing.patterns.push(...row.patterns)
        groups.set(key, existing)
    }

    return Array.from(groups.values())
}
