import type { CommentApi } from 'products/platform_features/frontend/generated/api.schemas'

import {
    TextCommentAnchor,
    buildArtifactCommentThreads,
    createTextCommentAnchor,
    resolveTextCommentAnchor,
} from './artifactComments'

function comment(overrides: Partial<CommentApi>): CommentApi {
    return {
        id: 'comment-1',
        created_by: null,
        completed_by: null,
        slack_thread: null,
        version: 0,
        created_at: '2026-09-30T18:00:00Z',
        completed_at: null,
        content: 'Looks good',
        scope: 'task_artifact',
        item_id: 'artifact-1',
        source_comment: null,
        ...overrides,
    }
}

describe('artifactComments', () => {
    it('reads thread state from Desktop resolve and reopen records and keeps them out of the replies', () => {
        const threads = buildArtifactCommentThreads([
            comment({
                id: 'root-pin',
                item_context: { anchor: { kind: 'region', x: 0.2, y: 0.3, width: 0.035, height: 0.035 } },
            }),
            comment({ id: 'reply', source_comment: 'root-pin', created_at: '2026-09-30T18:01:00Z' }),
            comment({
                id: 'resolve',
                source_comment: 'root-pin',
                content: 'Resolved this thread',
                created_at: '2026-09-30T18:02:00Z',
                item_context: { threadState: 'resolved' },
            }),
            comment({
                id: 'reopen',
                source_comment: 'root-pin',
                content: 'Reopened this thread',
                created_at: '2026-09-30T18:03:00Z',
                item_context: { threadState: 'open' },
            }),
            comment({
                id: 'root-doc',
                created_at: '2026-09-30T18:04:00Z',
                item_context: { anchor: { kind: 'document' } },
                completed_at: '2026-09-30T18:05:00Z',
            }),
        ])

        expect(
            threads.map(({ root, replies, resolved, pinNumber }) => ({
                id: root.id,
                replies: replies.map((reply) => reply.id),
                resolved,
                pinNumber,
            }))
        ).toEqual([
            { id: 'root-pin', replies: ['reply'], resolved: false, pinNumber: 1 },
            { id: 'root-doc', replies: [], resolved: true, pinNumber: null },
        ])
    })

    const DOCUMENT = 'Trial starts fell. The plan picker lost people. Fix the plan picker first.'
    const anchorFor = (quote: string, occurrence = 0): TextCommentAnchor => {
        let start = -1
        for (let index = 0; index <= occurrence; index++) {
            start = DOCUMENT.indexOf(quote, start + 1)
        }
        return createTextCommentAnchor(DOCUMENT, start, start + quote.length)!
    }

    it.each([
        {
            name: 'keeps the stored offsets when they still match',
            text: DOCUMENT,
            anchor: anchorFor('plan picker', 1),
            expected: { start: DOCUMENT.lastIndexOf('plan picker'), status: 'exact' },
        },
        {
            // Desktop renders markdown with a different component, so its offsets land elsewhere here.
            name: 'finds the quote again when the text before it changed',
            text: `# Report\n\n${DOCUMENT}`,
            anchor: anchorFor('Trial starts fell'),
            expected: { start: '# Report\n\n'.length, status: 'reanchored' },
        },
        {
            name: 'picks the repeat whose surrounding text matches',
            text: `Summary. ${DOCUMENT}`,
            anchor: anchorFor('plan picker', 1),
            expected: { start: `Summary. ${DOCUMENT}`.lastIndexOf('plan picker'), status: 'reanchored' },
        },
        {
            name: 'gives up on a repeat it cannot tell apart',
            text: 'plan picker and plan picker',
            anchor: { kind: 'text', quote: 'plan picker', prefix: 'x', suffix: 'y', start: 40, end: 51 },
            expected: null,
        },
    ] as const)('$name', ({ text, anchor, expected }) => {
        const resolved = resolveTextCommentAnchor(text, anchor as TextCommentAnchor)
        expect(resolved && { start: resolved.start, status: resolved.status }).toEqual(expected)
    })
})
