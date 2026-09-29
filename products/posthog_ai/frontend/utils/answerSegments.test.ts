import { splitAnswerSegments } from './answerSegments'

describe('splitAnswerSegments', () => {
    it.each([
        {
            name: 'saved insight and query blocks split the answer in order',
            text: 'Pageviews grew.\n<insight id="aB3xY" display="block"/>\nMost growth came from Chrome:\n<sql display="block" title="By browser">SELECT 1 &lt; 2</sql>',
            expected: [
                { type: 'markdown', text: 'Pageviews grew.\n' },
                { type: 'chart', block: { kind: 'insight', shortId: 'aB3xY' } },
                { type: 'markdown', text: '\nMost growth came from Chrome:\n' },
                { type: 'chart', block: { kind: 'hogql', query: 'SELECT 1 < 2', title: 'By browser' } },
            ],
        },
        {
            name: 'inline references stay in the markdown',
            text: 'See the <insight id="aB3xY">funnel</insight>.',
            expected: [{ type: 'markdown', text: 'See the <insight id="aB3xY">funnel</insight>.' }],
        },
        {
            name: 'a block tag inside a code fence stays literal',
            text: '```\n<insight id="aB3xY" display="block"/>\n```',
            expected: [{ type: 'markdown', text: '```\n<insight id="aB3xY" display="block"/>\n```' }],
        },
        {
            name: 'a block tag that is still streaming in stays in the markdown',
            text: 'Here:\n<hogql display="block" title="Daily">SELECT count()',
            expected: [{ type: 'markdown', text: 'Here:\n<hogql display="block" title="Daily">SELECT count()' }],
        },
    ])('$name', ({ text, expected }) => {
        expect(splitAnswerSegments(text)).toMatchObject(expected)
    })
})
