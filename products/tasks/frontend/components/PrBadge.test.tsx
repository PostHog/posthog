import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { initKeaTests } from '~/test/init'

import { PrBadge } from './PrBadge'

const PR_URL = 'https://github.com/PostHog/posthog/pull/12345'

describe('PrBadge', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders nothing when prUrl is undefined', () => {
        const { container } = render(<PrBadge prUrl={undefined} />)
        expect(container).toBeEmptyDOMElement()
    })

    it('renders a link to the PR opening in a new tab', () => {
        render(<PrBadge prUrl={PR_URL} />)
        const link = screen.getByRole('link')
        expect(link).toHaveAttribute('href', PR_URL)
        expect(link).toHaveAttribute('target', '_blank')
        expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'))
    })

    it('shows the PR number parsed from the url', () => {
        render(<PrBadge prUrl={PR_URL} />)
        expect(screen.getByText('View PR #12345')).toBeInTheDocument()
    })

    it('falls back to a plain label when the url has no PR number', () => {
        render(<PrBadge prUrl="https://github.com/PostHog/posthog/commits/main" />)
        expect(screen.getByText('View PR')).toBeInTheDocument()
    })

    it.each([
        [false, undefined],
        [true, undefined],
        [false, true],
        [true, true],
    ])('shows a spinner only when pending (isPending=%s, compact=%s)', (isPending, compact) => {
        const { container } = render(<PrBadge prUrl={PR_URL} isPending={isPending} compact={compact} />)
        expect(container.querySelector('.Spinner') !== null).toBe(isPending)
    })

    it('renders the compact variant as a small inline pill anchor', () => {
        render(<PrBadge prUrl={PR_URL} compact />)
        const link = screen.getByRole('link')
        expect(link).toHaveAttribute('href', PR_URL)
        expect(link).toHaveAttribute('target', '_blank')
        expect(link.className).toContain('text-[10px]')
        expect(link.className).toContain('inline-flex')
        expect(link.querySelector('.LemonButton')).toBeNull()
        expect(screen.getByText('View PR #12345')).toBeInTheDocument()
    })

    it.each([[true], [false]])('stops click propagation to parent handlers (compact=%s)', (compact) => {
        const onParentClick = jest.fn()
        render(
            <div onClick={onParentClick}>
                <PrBadge prUrl={PR_URL} compact={compact} />
            </div>
        )
        fireEvent.click(screen.getByRole('link'))
        expect(onParentClick).not.toHaveBeenCalled()
    })
})
