import { sendFromCodePrompt } from './sendFromCodePrompt'

const input = {
    projectToken: 'phc_test',
    host: 'https://us.i.posthog.com',
    secretKeysUrl: 'https://us.posthog.com/keys',
}

describe('sendFromCodePrompt', () => {
    it.each([
        ['a verified domain and a remote region', 'hello@example.com', 'https://eu.posthog.com', true],
        ['no verified domain on this app', null, null, false],
    ])('tells the agent about %s', (_case, from, appHost, named) => {
        const prompt = sendFromCodePrompt({ ...input, from, appHost })

        expect(prompt.includes('Send from hello@example.com.')).toBe(named)
        expect(prompt.includes('Leave out the from address.')).toBe(!named)
        expect(prompt.includes('app_host in Python: https://eu.posthog.com')).toBe(appHost !== null)
    })
})
