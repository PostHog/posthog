import { recipientTimelineQuery } from './recipientTimelineQuery'

describe('recipientTimelineQuery', () => {
    it('matches the address as an escaped, lower-cased string literal', () => {
        const query = recipientTimelineQuery(" O'Brien@Example.com ")

        expect(query).toContain("lower(properties.$email_to) = 'o\\'brien@example.com'")
        expect(query).toContain("lower(properties.$email) = 'o\\'brien@example.com'")
    })
})
