import { recipientEmailProperty } from './broadcastRecipientEmail'

describe('recipientEmailProperty', () => {
    it.each([
        { to: '{{ person.properties.email }}', expected: 'email' },
        { to: '{{person.properties.$email}}', expected: '$email' },
        { to: '  {{ person.properties.work_email }} ', expected: 'work_email' },
        { to: 'team@example.com', expected: null },
        { to: '{{ person.properties.email }}, team@example.com', expected: null },
        { to: '{{ person.properties.email | default: "x@example.com" }}', expected: null },
        { to: '', expected: null },
        { to: undefined, expected: null },
    ])('reads $expected from "$to"', ({ to, expected }) => {
        expect(recipientEmailProperty(to)).toEqual(expected)
    })
})
