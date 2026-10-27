import { variablesInEmail } from './emailVariables'

describe('variablesInEmail', () => {
    test.each([
        [
            'finds a variable in the body',
            { subject: 'Hi', html: '<a href="{{ variables.reset_link }}">Reset</a>' },
            ['reset_link'],
        ],
        [
            'keeps first-seen order across subject and body, without duplicates',
            { subject: 'Hi {{ variables.first_name }}', html: '{{variables.code}} {{ variables.first_name }}' },
            ['first_name', 'code'],
        ],
        ['reads past a Liquid filter', { subject: '{{ variables.name | default: "there" }}', html: '' }, ['name']],
        ['ignores person properties', { subject: '{{ person.properties.email }}', html: '' }, []],
    ])('%s', (_, email, expected) => {
        expect(variablesInEmail({ text: '', ...email })).toEqual(expected)
    })
})
