import '@testing-library/jest-dom'

import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { IssueSeveritySelect } from './IssueSeveritySelect'

describe('IssueSeveritySelect', () => {
    it('updates and clears the severity from the menu', async () => {
        const user = userEvent.setup()
        const onChange = jest.fn()
        const { rerender } = render(<IssueSeveritySelect severity="high" onChange={onChange} />)

        await user.click(screen.getByLabelText('Severity: High'))
        await user.click(await screen.findByText('Critical'))
        expect(onChange).toHaveBeenLastCalledWith('critical')

        rerender(<IssueSeveritySelect severity="critical" onChange={onChange} />)
        await user.click(screen.getByLabelText('Severity: Critical'))
        await user.click(await screen.findByText('No severity'))
        expect(onChange).toHaveBeenLastCalledWith(null)
    })
})
