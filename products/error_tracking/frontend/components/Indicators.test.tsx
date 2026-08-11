import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { IssueStatus, IssueStatusDot, StatusIndicator } from './Indicators'

describe('StatusIndicator', () => {
    it('shows the status explanation on hover when requested', async () => {
        render(<StatusIndicator status="active" withTooltip />)

        await userEvent.hover(screen.getByText('Active'))

        expect(await screen.findByText('Ongoing issue')).toBeInTheDocument()
    })

    it('renders a fallback instead of crashing for an unrecognized status', () => {
        render(<StatusIndicator status={'' as IssueStatus} />)

        expect(screen.getByText('Unknown')).toBeInTheDocument()
    })

    it('IssueStatusDot renders a fallback instead of crashing for an unrecognized status', () => {
        const { container } = render(<IssueStatusDot status={'' as IssueStatus} />)

        expect(container.firstChild).not.toBeNull()
    })
})
