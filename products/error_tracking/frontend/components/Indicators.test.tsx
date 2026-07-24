import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { StatusIndicator } from './Indicators'

describe('StatusIndicator', () => {
    it('shows the status explanation on hover when requested', async () => {
        render(<StatusIndicator status="active" withTooltip />)

        await userEvent.hover(screen.getByText('Active'))

        expect(await screen.findByText('Ongoing issue')).toBeInTheDocument()
    })
})
