import { EnrichedReviewer } from '../../types'
import { buildReviewerItems } from './SuggestedReviewersList'

function reviewer(
    id: string,
    explanation: string | null,
    sourceLabel: string,
    sourceSkill?: string | null
): EnrichedReviewer {
    return {
        github_login: id,
        user_uuid: id,
        github_name: id,
        relevant_commits:
            sourceLabel === 'Code history'
                ? [{ sha: 'abc123f', url: 'https://example.com/c/abc123f', reason: explanation ?? '' }]
                : [],
        user: null,
        source_skill: sourceSkill,
        source_label: sourceLabel,
        explanation,
    }
}

describe('buildReviewerItems', () => {
    it('groups exact repeated explanations only within the same source category', () => {
        const sharedReason = 'Maintains the request execution parser.'
        const items = buildReviewerItems([
            reviewer('avery', sharedReason, 'Runtime ownership scout', 'signals-scout-runtime-ownership'),
            reviewer('jordan', sharedReason, 'Code history', null),
            reviewer('morgan', sharedReason, 'Infrastructure scout', 'signals-scout-infrastructure'),
            reviewer('taylor', sharedReason, 'Code history', null),
            reviewer('rowan', `${sharedReason} `, 'Runtime ownership scout', 'signals-scout-runtime-ownership'),
            reviewer('casey', null, 'Agent suggestion', null),
        ])

        expect(items).toEqual([
            {
                kind: 'reason-group',
                key: JSON.stringify(['reason-group', sharedReason, 'scout', null]),
                reason: sharedReason,
                reviewers: [
                    reviewer('avery', sharedReason, 'Runtime ownership scout', 'signals-scout-runtime-ownership'),
                    reviewer('morgan', sharedReason, 'Infrastructure scout', 'signals-scout-infrastructure'),
                ],
            },
            {
                kind: 'reason-group',
                key: JSON.stringify(['reason-group', sharedReason, 'other', 'Code history']),
                reason: sharedReason,
                reviewers: [
                    reviewer('jordan', sharedReason, 'Code history', null),
                    reviewer('taylor', sharedReason, 'Code history', null),
                ],
            },
            {
                kind: 'person',
                key: 'rowan',
                reviewer: reviewer(
                    'rowan',
                    `${sharedReason} `,
                    'Runtime ownership scout',
                    'signals-scout-runtime-ownership'
                ),
            },
            {
                kind: 'person',
                key: 'casey',
                reviewer: reviewer('casey', null, 'Agent suggestion', null),
            },
        ])
    })
})
