import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { CitationTag } from './CitationTag'

describe('CitationTag', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        // Investigation citations map to the labeled "Query <n>" tag, unlinked — the findings
        // card carries the matching numbering on the same page.
        { citation: { type: 'query', ref: '2' }, text: 'Query 2', linked: false },
        { citation: { type: 'insight', ref: 'abc123' }, text: 'Insight abc123', linked: true },
        { citation: { type: 'signal_report', ref: 'x' }, text: 'signal_report:x', linked: false },
    ])('renders $citation.type as "$text" (linked: $linked)', ({ citation, text, linked }) => {
        render(
            <Provider>
                <CitationTag citation={citation} />
            </Provider>
        )
        const tag = screen.getByText(text)
        expect(tag).toBeInTheDocument()
        expect(Boolean(tag.closest('a'))).toBe(linked)
    })
})
