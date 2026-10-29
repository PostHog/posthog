import { MarkdownIt } from 'react-native-markdown-display'
import { objectTagsPlugin, objectWebUrl } from './objectTags'

const markdown = MarkdownIt({ html: false }).use(objectTagsPlugin)
const parse = (text: string) => markdown.parse(text, {})
const inline = (text: string) => parse(text).find((token) => token.type === 'inline')?.children ?? []
describe('object tags', () => {
    test('reads aliases and decoded attributes alongside formatted prose', () => {
        expect(
            inline('See **this** <feature_flag id="42" title="A &amp; B"/>').find(
                (token) => token.type === 'object_ref'
            )?.meta
        ).toEqual({ kind: 'flag', id: '42', label: 'A & B' })
    })
    test('renders unknown labels and leaves HTML literal', () => {
        expect(
            inline('x <gizmo id="1">Gizmo</gizmo>')
                .map((token) => token.content)
                .join('')
        ).toBe('x Gizmo')
        expect(
            inline('<b>bold</b>')
                .map((token) => token.content)
                .join('')
        ).toBe('<b>bold</b>')
    })
    test.each(['<insight', '<insight id="a', '<insight id="a">partial', '<insight id="a">partial</insi'])(
        'hides streaming tag %s',
        (text) => {
            expect(
                inline(`See ${text}`)
                    .map((token) => token.content)
                    .join('')
            ).toBe('See ')
        }
    )
    test('keeps malformed prose, code spans and fences literal', () => {
        expect(
            inline('See <insight, then y')
                .map((token) => token.content)
                .join('')
        ).toBe('See <insight, then y')
        expect(inline('`<insight id="a"/>`')[0]).toMatchObject({ type: 'code_inline', content: '<insight id="a"/>' })
        expect(parse('```\n<insight id="a" display="block"/>\n```')[0]).toMatchObject({ type: 'fence' })
    })
    test('hides malformed known markup but preserves following text', () => {
        expect(
            inline('See <insight id=x/> now')
                .map((token) => token.content)
                .join('')
        ).toBe('See  now')
    })
    test('block cards preserve multiline SQL and cap per message', () => {
        expect(parse('<hogql display="block" title="DAU">\nSELECT 1\n\nFROM events\n</hogql>')[0]?.meta).toEqual({
            mode: 'hogql',
            query: 'SELECT 1\n\nFROM events',
            title: 'DAU',
        })
        const text = Array.from({ length: 12 }, (_, i) => `<insight id="i${i}" display="block"/>`).join('\n\n')
        expect(parse(text).filter((token) => token.type === 'object_card')).toHaveLength(10)
        expect(parse(text).filter((token) => token.type === 'object_card')).toHaveLength(10)
        expect(inline('Look <insight id="a" display="block"/>').some((token) => token.type === 'object_ref')).toBe(true)
    })
    test('links use the selected host, project, aliases, guarded and encoded IDs', () => {
        expect(objectWebUrl('https://eu.posthog.com/', 7, 'insight', 'a/b')).toBe(
            'https://eu.posthog.com/project/7/insights/a%2Fb'
        )
        expect(objectWebUrl('https://example.com', 7, 'hogql', 'SELECT 1 & 2')).toBe(
            'https://example.com/project/7/sql?open_query=SELECT%201%20%26%202'
        )
        expect(objectWebUrl('https://example.com', 7, 'feature_flag', '42')).toBe(
            'https://example.com/project/7/feature-flags/42'
        )
        expect(objectWebUrl('https://example.com', 7, 'flag', 'beta')).toBeUndefined()
        expect(objectWebUrl('javascript:alert(1)', 7, 'insight', 'a')).toBeUndefined()
    })
})
