// Which pull requests a delivery surface covers: one author's, one GitHub team's, or one pull request.
// Mirrors the backend's DeliveryScope, so a page picks its scope once and every delivery logic and
// request below it agrees on it.

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

/** The query params the delivery endpoints read the scope from. */
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

/** A stable key for logics keyed by scope. */
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
