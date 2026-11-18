import type { AuthorFrictionApi, AuthorFrictionListApi } from '../generated/api.schemas'

function author(
    name: string,
    rank: number,
    [queue, review, ci, rework]: [number, number, number, number],
    teams: string[]
): AuthorFrictionApi {
    return {
        author: name,
        avatar_url: '',
        score: queue + review + ci + rework,
        groups: [
            { group: 'queue', score: queue },
            { group: 'review', score: review },
            { group: 'ci', score: ci },
            { group: 'rework', score: rework },
        ],
        pr_count: 12,
        rank,
        rank_low: Math.max(1, rank - 2),
        rank_high: rank + 4,
        teams,
    }
}

/** Story fixture for the friction read: invented authors, two of them on team-replay. */
export const FRICTION_STORY_FIXTURE: AuthorFrictionListApi = {
    available: true,
    window_days: 30,
    ranked_author_count: 5,
    github_team: null,
    has_membership_data: true,
    items: [
        author('jane-dev', 1, [1.4, 0.3, 0.6, 0.2], ['team-replay']),
        author('sam-ops', 2, [0.9, 0.6, 0.3, 0.2], ['team-infra']),
        author('li-web', 3, [0.5, 0.5, 0.2, 0.1], ['team-replay']),
        author('max-data', 4, [0.3, 0.2, 0.2, 0.1], ['team-replay']),
        author('ana-api', 5, [0.2, 0.2, 0.1, 0.1], ['team-infra']),
    ],
    teams: [{ github_team: 'team-replay', median_score: 1.3, scored_author_count: 3 }],
}
