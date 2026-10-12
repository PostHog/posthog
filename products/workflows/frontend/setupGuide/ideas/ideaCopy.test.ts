import { estimatedMonthlyCost, normalizeSite, SITE_PLACEHOLDER, withSite } from './ideaCopy'
import { ideaEmailSender, withEmailSender } from './ideaEmailSender'

describe('workflow idea helpers', () => {
    test.each([
        ['shop.example.com', 'https://shop.example.com'],
        ['  https://shop.example.com/  ', 'https://shop.example.com'],
        ['http://shop.example.com/pricing/', 'http://shop.example.com/pricing'],
        ['localhost', null],
        ['not a site', null],
        ['', null],
    ])('normalizeSite(%p) is %p', (input, expected) => {
        expect(normalizeSite(input)).toBe(expected)
    })

    test.each([
        [5_000, 0],
        [20_000, 30],
        [100_000, 180],
    ])('estimatedMonthlyCost(%p) is $%p', (emails, dollars) => {
        expect(estimatedMonthlyCost(emails)).toBe(dollars)
    })

    test('withSite points every button at the entered site', () => {
        const definition = {
            actions: [{ config: { html: `<a href="${SITE_PLACEHOLDER}/pricing">Plans</a>`, text: SITE_PLACEHOLDER } }],
        }

        expect(JSON.stringify(withSite(definition, 'https://shop.example.com'))).not.toContain(SITE_PLACEHOLDER)
        expect(JSON.stringify(withSite(definition, 'https://shop.example.com'))).toContain(
            'https://shop.example.com/pricing'
        )
    })

    test('withEmailSender sets the sender on email steps only and keeps the sender name', () => {
        const definition = {
            actions: [
                { type: 'trigger', config: {} },
                {
                    type: 'function_email',
                    config: { inputs: { email: { value: { from: { name: 'Example Store' }, subject: 'Hi' } } } },
                },
            ],
        }

        const result = withEmailSender(definition, 7) as { actions: Record<string, any>[] }

        expect(result.actions[0]).toEqual({ type: 'trigger', config: {} })
        expect(result.actions[1].config.inputs.email.value.from).toEqual({ name: 'Example Store', integrationId: 7 })
    })

    test.each([
        [null, 'unknown'],
        [[], 'none'],
        [[{ id: 1, kind: 'email', config: { verified: false } }], 'unverified'],
        [[{ id: 2, kind: 'email', config: { verified: true, email: 'hi@example.com' } }], 'verified'],
    ])('ideaEmailSender reads %p as %p', (integrations, status) => {
        expect(ideaEmailSender(integrations as any).status).toBe(status)
    })
})
