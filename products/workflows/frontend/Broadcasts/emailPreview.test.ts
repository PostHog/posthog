import { renderEmailPreview } from './emailPreview'

describe('renderEmailPreview', () => {
    const person = {
        id: 'person-1',
        properties: { email: 'sam@example.com', first_name: 'Sam' },
    }

    it.each([
        ['substitutes a property the person has', 'Hi {{ person.properties.first_name }}', 'Hi Sam'],
        [
            'keeps a property the person lacks visible instead of blanking it',
            'Hi {{ person.properties.nickname }}',
            'Hi {{ person.properties.nickname }}',
        ],
        ['keeps an unknown root visible', 'Your plan: {{ customer.plan_name }}', 'Your plan: {{ customer.plan_name }}'],
        [
            'leaves a filter to supply its own fallback',
            "Hi {{ person.properties.nickname | default: 'there' }}",
            'Hi there',
        ],
    ])('%s', (_name, template, expected) => {
        expect(renderEmailPreview(template, person)).toBe(expected)
    })

    it('decodes liquid tags the email editor escaped', () => {
        // Unlayer escapes the whole document, so a comparison arrives as &gt; and must still evaluate.
        expect(
            renderEmailPreview('{% if person.properties.age &gt; 20 %}adult{% endif %}', {
                id: 'person-2',
                properties: { age: 30 },
            })
        ).toBe('adult')
    })

    it('returns the template untouched when there is no person to render against', () => {
        expect(renderEmailPreview('Hi {{ person.properties.first_name }}', null)).toBe(
            'Hi {{ person.properties.first_name }}'
        )
    })

    it('falls back to the template rather than throwing on a broken tag', () => {
        expect(renderEmailPreview('{% for %}', person)).toBe('{% for %}')
    })
})
