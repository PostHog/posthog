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
        ['SQL alias', '<sql label="Result">SELECT 1</sql>', 'Result'],
        ['block title', '<hogql title="Daily signups" display="block">SELECT 1</hogql>', 'Daily signups'],
        ['empty block', '<replay id="example" display="block"/>', ''],
        ['XML entities', '<cohort id="1" title="New &amp; active">Users</cohort>', 'New & active'],
        ['repeated tags', '<insight id="1">One</insight> and <insight id="2">Two</insight>', 'One and Two'],
        ['unknown HTML', '<summary>Keep this</summary>', '<summary>Keep this</summary>'],
        ['code fence', '```xml\n<insight id="1">One</insight>\n```', '```xml\n<insight id="1">One</insight>\n```'],
        ['partial tag', 'Read <insight id="1">One', 'Read <insight id="1">One'],
        ['Slack mentions', '<@U000EXAMPLE|Example>', '<@U000EXAMPLE|Example>'],
        ['empty reply', '', ''],
    ])('handles %s', (_name, content, expected) => {
        expect(flattenObjectTags(content)).toBe(expected)
    })
})
