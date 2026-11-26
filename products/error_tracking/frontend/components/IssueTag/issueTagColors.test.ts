import { ISSUE_TAG_COLORS, issueTagColor } from './issueTagColors'

describe('issueTagColor', () => {
    it('keeps a chosen color', () => {
        expect(issueTagColor('Payments', 'teal')).toBe('teal')
    })

    it.each(['Payments', 'Checkout', '', 'A long tag name with ünïcode and spaces'])(
        'gives %p with no chosen color one of the named colors, the same one each time',
        (label) => {
            const color = issueTagColor(label, null)

            expect(ISSUE_TAG_COLORS).toContain(color)
            expect(issueTagColor(label, undefined)).toBe(color)
        }
    )
})
