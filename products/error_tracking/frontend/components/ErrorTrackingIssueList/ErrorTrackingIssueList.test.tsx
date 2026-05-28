import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { ErrorTrackingIssue } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { ErrorTrackingIssueList, ErrorTrackingIssueListRow } from './ErrorTrackingIssueList'
import { ErrorTrackingIssueListSkeleton } from './ErrorTrackingIssueListSkeleton'

jest.mock('../VolumeSparkline/VolumeSparkline', () => ({
    VolumeSparkline: (): JSX.Element => <div data-attr="mock-sparkline" />,
}))

const ISSUE: ErrorTrackingIssue = {
    id: 'issue-abc',
    name: 'TypeError: undefined is not a function',
    description: 'Something broke',
    library: 'web',
    status: 'active',
    assignee: null,
    first_seen: '2026-05-01T10:00:00.000Z',
    last_seen: '2026-05-26T08:00:00.000Z',
    aggregations: {
        occurrences: 12,
        sessions: 4,
        users: 3,
    },
}

describe('ErrorTrackingIssueListRow', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('links to the error tracking issue page with last_seen timestamp', () => {
        render(
            <Provider>
                <ErrorTrackingIssueListRow issue={ISSUE} />
            </Provider>
        )

        const link = screen.getByRole('link', { name: /TypeError: undefined is not a function/i })
        expect(link.getAttribute('href')).toMatch(
            /\/error_tracking\/issue-abc\?timestamp=2026-05-26T08%3A00%3A00\.000Z$/
        )
    })

    it('renders a non-link row when disableLink is true', () => {
        render(
            <Provider>
                <ErrorTrackingIssueListRow issue={ISSUE} disableLink />
            </Provider>
        )

        expect(screen.queryByRole('link')).not.toBeInTheDocument()
        expect(screen.getByText('TypeError: undefined is not a function')).toBeInTheDocument()
    })
})

describe('ErrorTrackingIssueListSkeleton', () => {
    it('renders accessible loading state with skeleton rows', () => {
        const { container } = render(<ErrorTrackingIssueListSkeleton rowCount={3} />)

        expect(screen.getByLabelText('Loading issues')).toHaveAttribute('aria-busy', 'true')
        expect(container.querySelectorAll('[aria-hidden]').length).toBeGreaterThanOrEqual(3)
    })
})

describe('ErrorTrackingIssueList', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('renders non-link rows when disableLinks is true', () => {
        render(
            <Provider>
                <ErrorTrackingIssueList issues={[ISSUE]} disableLinks />
            </Provider>
        )

        expect(screen.queryByRole('link')).not.toBeInTheDocument()
        expect(screen.getByText('TypeError: undefined is not a function')).toBeInTheDocument()
    })
})
