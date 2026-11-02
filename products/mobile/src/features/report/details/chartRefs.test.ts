import { createMarkdownIt } from '@/lib/markdownIt'

import { chartRefsPlugin } from './chartRefs'

const markdownIt = createMarkdownIt().use(chartRefsPlugin)

describe('chartRefsPlugin', () => {
    test.each([
        [
            'an inline reference reads as its label',
            'See [the trend](chart:load-time) here.',
            '<p>See the trend here.</p>\n',
        ],
        [
            'a paragraph of references only is dropped',
            'Before.\n\n[Load time](chart:load-time)\n[By browser](chart:by-browser)\n\nAfter.',
            '<p>Before.</p>\n<p>After.</p>\n',
        ],
        [
            'a reference-style link to a chart reads as its label',
            'The [step up][load] is the deploy.\n\n[load]: chart:load-time',
            '<p>The step up is the deploy.</p>\n',
        ],
        [
            'a reference in a code span stays literal',
            'Write `[x](chart:a)` to place a chart.',
            '<p>Write <code>[x](chart:a)</code> to place a chart.</p>\n',
        ],
        [
            'other links stay links',
            'Read [the PR](https://example.com/pull/1).',
            '<p>Read <a href="https://example.com/pull/1">the PR</a>.</p>\n',
        ],
    ])('%s', (_case, source, html) => {
        expect(markdownIt.render(source)).toBe(html)
    })
})
