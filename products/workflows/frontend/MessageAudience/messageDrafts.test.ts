import { draftMessage, messageDraftEmail, parseMessageDraftPrefill } from './messageDrafts'

describe('messageDrafts', () => {
    it('escapes a feature name in the html and design but keeps it as typed in the subject and text', () => {
        const draft = draftMessage({
            kind: 'feature_available',
            featureName: 'Beta <script>alert(1)</script> & co',
            featureDescription: '',
        })
        const email = messageDraftEmail(parseMessageDraftPrefill(JSON.stringify(draft))!)

        expect(email.subject).toEqual('Beta <script>alert(1)</script> & co is now available')
        expect(email.text).toContain('try Beta <script>alert(1)</script> & co early')
        expect(email.html).not.toContain('<script>')
        expect(email.html).toContain('Beta &lt;script&gt;alert(1)&lt;/script&gt; &amp; co')
        expect(JSON.stringify(email.design)).not.toContain('<script>')
        expect(email.text.split('\n\n')).toEqual(draft.paragraphs)
    })

    it.each([
        ['nothing', undefined],
        ['a non-JSON string', 'not-json'],
        ['a missing subject', '{"paragraphs":["Hi"]}'],
        ['an empty subject', '{"subject":" ","paragraphs":["Hi"]}'],
        ['no paragraphs', '{"subject":"Hi","paragraphs":[]}'],
        ['a paragraph that is not text', '{"subject":"Hi","paragraphs":[{"html":"<b>x</b>"}]}'],
        [
            'a subject longer than an email subject can be',
            JSON.stringify({ subject: 'x'.repeat(301), paragraphs: ['Hi'] }),
        ],
    ])('ignores a link with %s', (_label, raw) => {
        expect(parseMessageDraftPrefill(raw)).toBeNull()
    })
})
