import { EnrichedReviewer } from '../../types'
import { buildReviewerItems } from './SuggestedReviewersList'

function reviewer(id: string, explanation: string | null, sourceLabel: string): EnrichedReviewer {
    return {
        github_login: id,
        user_uuid: id,
        github_name: id,
        relevant_commits: [],
        user: null,
        source_label: sourceLabel,
        explanation,
    }
}

describe('buildReviewerItems', () => {
    it('groups only exact repeated explanations and keeps unique reviewers separate', () => {
        const sharedReason = 'Maintains the request execution parser.'
        const items = buildReviewerItems([
            reviewer('avery', sharedReason, 'Runtime ownership scout'),
            reviewer('jordan', sharedReason, 'Code history'),
            reviewer('rowan', `${sharedReason} `, 'Runtime ownership scout'),
            reviewer('casey', null, 'Agent suggestion'),
        ])

        expect(items).toEqual([
            {
                kind: 'reason-group',
                key: JSON.stringify(['reason-group', sharedReason]),
                reason: sharedReason,
                reviewers: [
                    reviewer('avery', sharedReason, 'Runtime ownership scout'),
                    reviewer('jordan', sharedReason, 'Code history'),
                ],
                sourceLabels: ['Runtime ownership scout', 'Code history'],
            },
            {
                kind: 'person',
                key: 'rowan',
                reviewer: reviewer('rowan', `${sharedReason} `, 'Runtime ownership scout'),
            },
            {
                kind: 'person',
                key: 'casey',
                reviewer: reviewer('casey', null, 'Agent suggestion'),
            },
        ])
    })
})
