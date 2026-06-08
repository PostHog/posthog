import '@testing-library/jest-dom'

import { cleanup, render } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { type NotableSession } from '../mcpDashboardOverviewLogic'
import { NotableSessionsTable } from './NotableSessionsTable'

const SESSIONS: NotableSession[] = [
    {
        rule: 'worst_error_rate',
        label: 'Worst error rate at high volume',
        session: {
            session_id: 'abcd1234efgh5678',
            tool_calls: 47,
            errors: 13,
            error_rate_pct: 28,
            duration_seconds: 2335,
            distinct_tools: 5,
            last_seen: '',
        },
    },
    {
        rule: 'exemplar',
        label: 'Exemplar — concise success',
        session: {
            session_id: 'short',
            tool_calls: 12,
            errors: 0,
            error_rate_pct: 0,
            duration_seconds: 40,
            distinct_tools: 3,
            last_seen: '',
        },
    },
]

describe('NotableSessionsTable', () => {
    beforeEach(() => initKeaTests())
    afterEach(() => cleanup())

    function renderTable(sessions: NotableSession[], loading: boolean): ReturnType<typeof render> {
        return render(
            <Provider>
                <NotableSessionsTable sessions={sessions} loading={loading} />
            </Provider>
        )
    }

    it('renders a row per flagged session with status and footer link', () => {
        const { container } = renderTable(SESSIONS, false)
        expect(container).toMatchSnapshot()
    })

    it('renders the empty state', () => {
        const { container } = renderTable([], false)
        expect(container).toMatchSnapshot()
    })

    it('renders loading skeletons', () => {
        const { container } = renderTable([], true)
        expect(container).toMatchSnapshot()
    })
})
