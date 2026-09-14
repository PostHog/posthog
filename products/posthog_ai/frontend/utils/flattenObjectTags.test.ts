import { flattenObjectTags } from './flattenObjectTags'

describe('flattenObjectTags', () => {
    it.each([
        'insight',
        'dashboard',
        'error',
        'replay',
        'flag',
        'experiment',
        'survey',
        'ticket',
        'report',
        'trace',
        'eval',
        'event',
        'cohort',
        'action',
        'person',
        'session-replay',
        'recording',
        'feature-flag',
        'feature_flag',
    ])('keeps the display label for %s', (kind) => {
        expect(flattenObjectTags(`Read <${kind} id="example">the result</${kind}>.`)).toBe('Read the result.')
    })

    it.each([
        ['SQL label', '<hogql label="Result">SELECT 1</hogql>', 'Result'],
        ['SQL without a label', '<hogql>SELECT 1</hogql>', 'SQL query'],
        ['SQL alias without a label', '<sql>SELECT 1</sql>', 'SQL query'],
        ['SQL alias', '<sql label="Result">SELECT 1</sql>', 'Result'],
        ['block title', '<hogql title="Daily signups" display="block">SELECT 1</hogql>', 'Daily signups'],
        ['empty block', '<replay id="example" display="block"/>', ''],
        ['XML entities', '<cohort id="1" title="New &amp; active">Users</cohort>', 'New & active'],
        ['repeated tags', '<insight id="1">One</insight> and <insight id="2">Two</insight>', 'One and Two'],
        ['unknown HTML', '<summary>Keep this</summary>', '<summary>Keep this</summary>'],
        ['code fence', '```xml\n<insight id="1">One</insight>\n```', '```xml\nOne\n```'],
        ['partial tag', 'Read <insight id="1">One', 'Read <insight id="1">One'],
        ['Slack mentions', '<@U000EXAMPLE|Example>', '<@U000EXAMPLE|Example>'],
        ['tilde_fence', '~~~xml\n<insight id="1">Example</insight>\n~~~', '~~~xml\nExample\n~~~'],
        ['open_fence', '```xml\n<insight id="1">Example</insight>', '```xml\nExample'],
        ['long_fence', '````xml\n```\n<insight id="1">Example</insight>\n````', '````xml\n```\nExample\n````'],
        ['indented_code', '    <insight id="1">Example</insight>\n', '    Example\n'],
        ['tab_indented_code', '\t<insight id="1">Example</insight>\n', '\tExample\n'],
        ['quoted_fence', '> ```xml\n> <insight id="1">Example</insight>\n> ```', '> ```xml\n> Example\n> ```'],
        ['double_backtick', 'Use ``<insight id="1">Example</insight>``.', 'Use ``Example``.'],
        ['multiline_inline_code', 'Use ``one\n<insight id="1">Example</insight>\ntwo``.', 'Use ``one\nExample\ntwo``.'],
        [
            'mixed code and prose',
            'Read <insight id="1">One</insight>.\n\n~~~xml\n<insight id="1">Example</insight>\n~~~\n\nRead <insight id="2">Two</insight>.',
            'Read One.\n\n~~~xml\nExample\n~~~\n\nRead Two.',
        ],
        ['empty reply', '', ''],
    ])('handles %s', (_name, content, expected) => {
        expect(flattenObjectTags(content)).toBe(expected)
    })
})
