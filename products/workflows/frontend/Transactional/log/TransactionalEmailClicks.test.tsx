import { cleanup, render, screen } from '@testing-library/react'

import { EmailClickLinks } from './emailClicks'
import { TransactionalEmailClicks } from './TransactionalEmailClicks'

describe('TransactionalEmailClicks', () => {
    afterEach(() => {
        cleanup()
    })

    it.each([
        ['says the link was never recorded once the links loaded', 'loaded', 'Link not recorded'],
        ['says the link was never recorded for a send without a distinct ID', 'none', 'Link not recorded'],
        ["says the link didn't load when the request failed", 'failed', 'Link not loaded'],
    ] as const)('%s', (_name, links: EmailClickLinks, text) => {
        render(
            <TransactionalEmailClicks
                rows={[{ key: 'a', at: '2026-06-15T09:05:00Z', link: null }]}
                links={links}
                moreClicks={false}
                onRetry={() => {}}
            />
        )

        expect(screen.getByText(text)).toBeTruthy()
    })

    it('shows a clicked link as text that never opens', () => {
        const { container } = render(
            <TransactionalEmailClicks
                rows={[{ key: 'a', at: '2026-06-15T09:05:00Z', link: 'https://example.com/billing' }]}
                links="loaded"
                moreClicks={false}
                onRetry={() => {}}
            />
        )

        expect(screen.getByTitle('https://example.com/billing')).toBeTruthy()
        expect(container.querySelector('a')).toBeNull()
    })
})
