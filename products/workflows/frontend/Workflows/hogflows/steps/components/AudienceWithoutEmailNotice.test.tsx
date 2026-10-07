import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { initKeaTests } from '~/test/init'
import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

import { AudienceWithoutEmailNotice } from './AudienceWithoutEmailNotice'

const AUDIENCE_PROPERTIES: AnyPropertyFilter[] = [
    { key: 'plan', type: PropertyFilterType.Person, value: ['pro'], operator: PropertyOperator.Exact },
]

describe('AudienceWithoutEmailNotice', () => {
    beforeEach(() => {
        initKeaTests()
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags(['workflows-missing-email-warning'], {
            'workflows-missing-email-warning': true,
        })
    })
    afterEach(cleanup)

    it('hides an earlier count when the feature flag is disabled', () => {
        featureFlagLogic.actions.setFeatureFlags([], { 'workflows-missing-email-warning': false })
        const { container } = render(<AudienceWithoutEmailNotice withoutEmail={12} audienceProperties={[]} />)
        expect(container).toBeEmptyDOMElement()
    })

    it.each([
        ['the count was not taken', null],
        ['everyone has an email', 0],
    ])('renders nothing when %s', (_name, withoutEmail) => {
        const { container } = render(<AudienceWithoutEmailNotice withoutEmail={withoutEmail} audienceProperties={[]} />)
        expect(container).toBeEmptyDOMElement()
    })

    it.each([
        [1, '1 person in this audience has no email address and will not get the email.'],
        [1342, 'About 1,342 people in this audience have no email address and will not get the email.'],
    ])('names the %s unreachable people and links to them', (withoutEmail, text) => {
        render(<AudienceWithoutEmailNotice withoutEmail={withoutEmail} audienceProperties={AUDIENCE_PROPERTIES} />)

        expect(screen.getByText(text)).toBeInTheDocument()
        const link = screen.getByTestId('audience-without-email-link')
        expect(link).toHaveAttribute('target', '_blank')
        const href = decodeURIComponent(link.getAttribute('href') ?? '')
        expect(href).toContain('/persons')
        expect(href).toContain('"key":"plan"')
        expect(href).toContain(
            `"type":"hogql","key":"isNull(properties.email) OR trim(toString(properties.email)) = ''"`
        )
    })
})
