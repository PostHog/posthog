import { describeSendError, findMergeTag } from './broadcastSendError'

describe('broadcastSendError', () => {
    it.each([
        {
            name: 'a merge tag inside a link',
            log: '[Action:email_1] Errored: Error: invalid value expression: "%20person.properties.city%20|%20url_enco...", line:98, col:158',
            expected: {
                kind: 'content',
                reason: 'A merge tag in a link is broken',
                tag: 'person.properties.city | url_enco...',
                nextStep: 'Edit the link and type the tag again.',
            },
        },
        {
            name: 'a merge tag outside a link',
            log: '[Action:email_1] Errored: Error: invalid value expression: "person.properties.city |", line:3, col:9',
            expected: {
                kind: 'content',
                reason: "A merge tag can't be read",
                tag: '{{ person.properties.city | }}',
                nextStep: 'Check the tag in the email for typos.',
            },
        },
        {
            name: 'a sender that no longer exists',
            log: '[Action:email_1] Errored: Error: Email integration not found. The sender configured for this step no longer exists.',
            expected: {
                kind: 'content',
                reason: "The sender for this email isn't set up",
                tag: null,
                nextStep: 'Check the sender in the email step and that its domain is verified, then send it again.',
            },
        },
        {
            name: 'an SES rejection for an unverified sender address',
            log: '[Action:email_1] Errored: Error: Failed to send email via SES: Email address is not verified. The following identities failed the check: hello@example.com',
            expected: {
                kind: 'content',
                reason: "The sender for this email isn't set up",
                tag: null,
                nextStep: 'Check the sender in the email step and that its domain is verified, then send it again.',
            },
        },
        {
            name: 'a timeout on our side',
            log: '[Action:email_1] Errored: Error: Request to the template service timed out after 10000ms',
            expected: { kind: 'our_side', reason: 'A problem on our side stopped the send', tag: null, nextStep: null },
        },
        {
            name: 'an error nothing recognizes',
            log: '[Action:email_1] Errored: Error: Unexpected token in template',
            expected: {
                kind: 'unknown',
                reason: 'Sending hit an error',
                tag: null,
                nextStep: 'Show details has the error from the send.',
            },
        },
    ])('describes $name', ({ log, expected }) => {
        expect(describeSendError(log, 'email')).toEqual(expected)
    })

    it.each([
        {
            name: 'recovers a truncated tag from URL-encoded link content',
            tag: 'person.properties.city | url_enco...',
            content: '<a href="https://example.com/?c={{%20person.properties.city%20|%20url_encode%20}}">Hi</a>',
            expected: '{{ person.properties.city | url_encode }}',
        },
        {
            name: 'keeps a truncated tag when no tag in the content matches',
            tag: 'person.properties.city | url_enco...',
            content: '<p>Hello {{ person.properties.first_name }}</p>',
            expected: 'person.properties.city | url_enco...',
        },
    ])('$name', ({ tag, content, expected }) => {
        expect(findMergeTag(tag, content)).toBe(expected)
    })
})
