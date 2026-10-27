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
        [
            'finds a variable in a control tag',
            { subject: '', html: '{% if variables.show_receipt %}Hi{% endif %}' },
            ['show_receipt'],
        ],
        [
            'finds a variable used as a filter argument',
            { subject: '{{ variables.name | default: variables.fallback_name }}', html: '' },
            ['name', 'fallback_name'],
        ],
        ['ignores the word outside Liquid', { subject: 'See variables.example in the docs', html: '' }, []],
        [
            'finds a variable in the sender name and reply-to',
            {
                subject: '',
                html: '',
                from: { name: '{{ variables.sender_name }}' },
                replyTo: '{{ variables.reply_to }}',
            },
            ['sender_name', 'reply_to'],
        ],
    ])('%s', (_, email, expected) => {
        expect(variablesInEmail({ text: '', from: '', ...email })).toEqual(expected)
    })
})
