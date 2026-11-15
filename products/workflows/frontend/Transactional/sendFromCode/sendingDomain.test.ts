import { senderAddress } from './sendingDomain'

describe('senderAddress', () => {
    test.each([
        ['Acme', 'Acme <hello@example.com>'],
        ['Acme, Inc.', '"Acme, Inc." <hello@example.com>'],
        [`Bob's "Shop"`, `"Bob's \\"Shop\\"" <hello@example.com>`],
        [undefined, 'hello@example.com'],
    ])('writes the sender named %p the way the send API parses it', (name, expected) => {
        expect(senderAddress(name, 'hello@example.com')).toEqual(expected)
    })
})
