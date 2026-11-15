import { SendFromCodeSdk, SendFromCodeSnippetInput, sendFromCodeSnippet } from './sendFromCodeSnippets'

const SENDER = `"Bob's \\"Shop\\"\nOutlet" <hello@example.com>`

const input = (from: string | null): SendFromCodeSnippetInput => ({
    projectToken: 'phc_test',
    host: 'https://us.i.posthog.com',
    appHost: null,
    sendUrl: 'https://us.posthog.com/api/projects/1/messaging/send/email/',
    from,
})

const senderAsEachLanguageReadsIt: Record<SendFromCodeSdk, (code: string) => string | undefined> = {
    node: (code) => {
        const literal = code.match(/^\s+from: (.*),$/m)?.[1]
        return literal === undefined ? undefined : new Function(`return ${literal}`)()
    },
    python: (code) => {
        const literal = code.match(/^\s+from_=(.*),$/m)?.[1]
        return literal === undefined ? undefined : JSON.parse(literal)
    },
    curl: (code) => {
        let rest = code.slice(code.indexOf('-d ') + 3)
        let body = ''
        while (rest.startsWith("'")) {
            const end = rest.indexOf("'", 1)
            body += rest.slice(1, end)
            rest = rest.slice(end + 1)
            if (!rest.startsWith("\\'")) {
                break
            }
            body += "'"
            rest = rest.slice(2)
        }
        return JSON.parse(body).from
    },
}

describe('sendFromCodeSnippet', () => {
    test.each<SendFromCodeSdk>(['node', 'python', 'curl'])('keeps a quoted sender intact in %s', (sdk) => {
        expect(senderAsEachLanguageReadsIt[sdk](sendFromCodeSnippet(sdk, input(SENDER)).code)).toEqual(SENDER)
    })

    test.each<SendFromCodeSdk>(['node', 'python', 'curl'])('leaves the sender out in %s without one', (sdk) => {
        expect(senderAsEachLanguageReadsIt[sdk](sendFromCodeSnippet(sdk, input(null)).code)).toBeUndefined()
    })
})
