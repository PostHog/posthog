import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { IssueSeveritySelect } from './IssueSeveritySelect'

describe('IssueSeveritySelect', () => {
    it('updates severity without offering a clear action', async () => {
        const user = userEvent.setup()
        const onChange = jest.fn()
        render(<IssueSeveritySelect severity="high" onChange={onChange} />)

        await user.click(screen.getByLabelText('Severity: High'))
        expect(screen.queryByText('No severity')).not.toBeInTheDocument()

        await user.click(await screen.findByText('Critical'))
        expect(onChange).toHaveBeenLastCalledWith('critical')
    })
})
