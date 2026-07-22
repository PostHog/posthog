jest.mock('@posthog/mcp-ui', () => ({ DescriptionList: () => null }), { virtual: true })
jest.mock('@posthog/quill', () => ({ Button: () => null, Card: () => null, CardContent: () => null }), {
    virtual: true,
})
jest.mock('lucide-react', () => ({ Check: () => null }), { virtual: true })

import { describeFixReviewComments, type LoopReviewBehaviors } from './LoopReviewView'

describe('describeFixReviewComments', () => {
    it.each<[string, LoopReviewBehaviors | undefined, string]>([
        ['fix_review_comments without watch_ci', { fix_review_comments: true, watch_ci: false }, 'Yes'],
        ['fix_review_comments with watch_ci', { fix_review_comments: true, watch_ci: true }, 'Yes'],
        ['watch_ci only', { fix_review_comments: false, watch_ci: true }, 'No'],
        ['neither flag', { fix_review_comments: false, watch_ci: false }, 'No'],
        ['missing behaviors', undefined, 'No'],
        ['iteration cap', { fix_review_comments: true, max_fix_iterations: 5 }, 'Yes (up to 5 iterations)'],
    ])('%s', (_label, behaviors, expected) => {
        expect(describeFixReviewComments(behaviors)).toBe(expected)
    })
})
