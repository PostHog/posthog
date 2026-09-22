import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { DetailSection } from './DetailSection'

describe('DetailSection', () => {
    it('renders a summary for the current open state', async () => {
        const user = userEvent.setup()

        render(
            <DetailSection
                icon={<span />}
                title="Example section"
                collapsible
                defaultCollapsed
                summary={(open) => (open ? 'Open summary' : 'Closed summary')}
            >
                Section body
            </DetailSection>
        )

        expect(screen.getByText('Closed summary')).toBeInTheDocument()
        expect(screen.queryByText('Open summary')).not.toBeInTheDocument()
        expect(screen.queryByText('Section body')).not.toBeInTheDocument()

        await user.click(screen.getByRole('button', { name: /Example section/i }))

        expect(screen.getByText('Open summary')).toBeInTheDocument()
        expect(screen.queryByText('Closed summary')).not.toBeInTheDocument()
        expect(screen.getByText('Section body')).toBeInTheDocument()
    })
})
