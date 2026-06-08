import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'

import { HarnessPill } from './harness'

describe('HarnessPill', () => {
    afterEach(() => cleanup())

    it('renders a known harness with its logo', () => {
        const { container } = render(<HarnessPill category="Claude Code" />)
        expect(container).toMatchSnapshot()
    })

    it('renders an unknown harness with a fallback dot', () => {
        const { container } = render(<HarnessPill category="Mystery Client" title="mystery-client/1.0" />)
        expect(container).toMatchSnapshot()
    })
})
