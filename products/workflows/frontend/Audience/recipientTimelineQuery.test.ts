import { recipientTimelineQuery } from './recipientTimelineQuery'

describe('recipientTimelineQuery', () => {
    it('matches the address with utf-8 lower-casing on both sides, as an escaped literal', () => {
        const query = recipientTimelineQuery(" O'Brien.MÜLLER@Example.com ")

        expect(query).toContain("lowerUTF8(properties.$email_to) = 'o\\'brien.müller@example.com'")
        expect(query).toContain("lowerUTF8(properties.$email) = 'o\\'brien.müller@example.com'")
    })
})
