import { render } from '@testing-library/react'

import { EmailDocumentPreview } from './EmailDocumentPreview'

const ADA = { id: 'ada', displayName: 'Ada', properties: { first_name: 'Ada', plan: 'pro' } }
const HTML =
    '<p>{{ person.properties.first_name | upcase }}</p>{% if person.properties.plan == "pro" %}<p>Pro</p>{% else %}<p>Free</p>{% endif %}'

function previewText(html: string, liquid: boolean, person: typeof ADA | null): string {
    const { container } = render(
        <EmailDocumentPreview html={html} liquid={liquid} person={person} onPersonChange={() => {}} />
    )
    const srcDoc = container.querySelector('[data-attr="email-editor-preview-frame"]')?.getAttribute('srcdoc') ?? ''
    return new DOMParser().parseFromString(srcDoc, 'text/html').body.textContent ?? ''
}

describe('EmailDocumentPreview', () => {
    it.each([
        ['no one picked runs conditions without properties', true, null, 'Free'],
        ['a picked person fills filters and conditions', true, ADA, 'ADAPro'],
        ['an email that is not Liquid ignores the picked person', false, ADA, HTML.replace(/<[^>]+>/g, '')],
    ])('%s', (_, liquid, person, expected) => {
        expect(previewText(HTML, liquid, person)).toBe(expected)
    })
})
