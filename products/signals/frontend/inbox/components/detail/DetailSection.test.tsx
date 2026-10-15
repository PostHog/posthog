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
                meta={(open) => (open ? null : 'Closed summary')}
                summary={(open) => (open ? 'Open summary' : null)}
            >
                Section body
            </DetailSection>
        )

        const toggle = screen.getByText('Example section').closest('button')
        if (!toggle) {
            throw new Error('Expected section title to be inside a button')
        }

        expect(screen.getByText('Closed summary')).toBeInTheDocument()
        expect(toggle).toHaveTextContent('Closed summary')
        expect(screen.queryByText('Open summary')).not.toBeInTheDocument()
        expect(screen.queryByText('Section body')).not.toBeInTheDocument()

        await user.click(toggle)

        expect(screen.getByText('Open summary')).toBeInTheDocument()
        expect(screen.queryByText('Closed summary')).not.toBeInTheDocument()
        expect(toggle).not.toHaveTextContent('Open summary')
        expect(screen.getByText('Section body')).toBeInTheDocument()
    })
})
