import { stripObjectTags } from './stripObjectTags'

describe('stripObjectTags', () => {
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
    ])('removes the entire %s element', (kind) => {
        expect(stripObjectTags(`Before <${kind} id="example">hidden label</${kind}> after.`)).toBe('Before  after.')
    })

    it.each([
        ['SQL payload and title', '<hogql title="Daily signups" label="Fallback" display="block">SELECT 1</hogql>', ''],
        ['SQL alias', '<sql>SELECT 1</sql>', ''],
        ['self-closing block', '<replay id="example" title="Recording" display="block"/>', ''],
        ['single-quoted attributes', "<insight id='example'>Hidden</insight>", ''],
        ['nested same kind', '<insight>outer<insight>inner</insight>tail</insight>Kept', 'Kept'],
        ['nested other kind', '<insight>outer<report>inner</report>tail</insight>Kept', 'Kept'],
        ['consecutive elements', '<insight>One</insight><hogql>SELECT 1</hogql>Kept', 'Kept'],
        ['unfinished body', 'Before <hogql title="Hidden">SELECT', 'Before '],
        ['stray closing tag', 'Before </insight> after', 'Before  after'],
        ['inline code', 'Use `<insight>Hidden</insight>`.', 'Use ``.'],
        ['fenced code', '```xml\n<insight>Hidden</insight>\n```', '```xml\n\n```'],
        ['mixed code', '~~~\nKeep this.\n<insight>Hidden</insight>\n~~~', '~~~\nKeep this.\n\n~~~'],
        ['unknown markup', '<summary>Keep this</summary>', '<summary>Keep this</summary>'],
        ['Slack mention', '<@U000EXAMPLE|Example>', '<@U000EXAMPLE|Example>'],
        ['empty text', '', ''],
    ])('handles %s', (_name, content, expected) => {
        expect(stripObjectTags(content)).toBe(expected)
    })
})
