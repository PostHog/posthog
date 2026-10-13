// Mirrors the backend's DeliveryScope; keep the kinds and query params in sync.

export type DeliveryScope =
    | { kind: 'author'; author: string }
    | { kind: 'github_team'; githubTeam: string }
    | { kind: 'pull_request'; prNumber: number; repo: string }

export interface DeliveryScopeParams {
    author?: string
    github_team?: string
    pr_number?: number
    repo?: string
}

export function deliveryScopeParams(scope: DeliveryScope): DeliveryScopeParams {
    switch (scope.kind) {
        case 'author':
            return { author: scope.author }
        case 'github_team':
            return { github_team: scope.githubTeam }
        case 'pull_request':
            return { pr_number: scope.prNumber, repo: scope.repo }
    }
}

export function deliveryScopeKey(scope: DeliveryScope): string {
    switch (scope.kind) {
        case 'author':
            return `author:${scope.author}`
        case 'github_team':
            return `team:${scope.githubTeam}`
        case 'pull_request':
            return `pr:${scope.repo}#${scope.prNumber}`
    }
}
