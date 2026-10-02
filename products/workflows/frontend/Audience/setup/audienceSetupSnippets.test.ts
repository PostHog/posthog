import { posthogNodeSnippet } from './audienceSetupSnippets'

describe('posthogNodeSnippet', () => {
    it.each([
        { topicKey: "it's-news", entry: "'it\\'s-news': false" },
        { topicKey: 'back\\slash', entry: "'back\\\\slash': false" },
    ])('writes the topic key $topicKey as a valid object key', ({ topicKey, entry }) => {
        const snippet = posthogNodeSnippet({
            projectToken: 'phc_test',
            host: 'https://us.i.posthog.com',
            topicKeys: [topicKey],
        })

        expect(snippet).toContain(entry)
    })
})
