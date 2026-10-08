import { recipientEmailProperties, recipientEmailProperty } from './recipientEmail'

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

    it('lists each property the email steps send to once', () => {
        const email = (to: string): any => ({
            type: 'function_email',
            config: { inputs: { email: { value: { to: { email: to } } } } },
        })
        const workflow = {
            actions: [
                email('{{ person.properties.email }}'),
                email('{{ person.properties.$email }}'),
                email('{{ person.properties.email }}'),
                email('team@example.com'),
                { type: 'delay', config: {} } as any,
            ],
        }
        expect(recipientEmailProperties(workflow)).toEqual(['$email', 'email'])
    })
})
