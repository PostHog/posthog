import '@testing-library/jest-dom'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Provider } from 'kea'

import { getByDataAttr } from '~/test/byDataAttr'
import { initKeaTests } from '~/test/init'

import { TimezoneSelect } from './TimezoneSelect'

function renderTimezoneSelect(props: { value: string; onChange: jest.Mock; additionalTimezones?: string[] }): {
    container: HTMLElement
    getSelect: () => HTMLElement
} {
    const { container } = render(
        <Provider>
            <TimezoneSelect {...props} />
        </Provider>
    )
    return {
        container,
        getSelect: () => getByDataAttr(container, 'timezone-select'),
    }
}

describe('TimezoneSelect', () => {
    beforeEach(() => {
        initKeaTests()
    })

    it('renders with UTC selected by default', () => {
        const onChange = jest.fn()
        const { getSelect } = renderTimezoneSelect({ value: 'UTC', onChange })

        expect(within(getSelect()).getByText('UTC')).toBeInTheDocument()
    })

    it('shows Local option in dropdown', async () => {
        const onChange = jest.fn()
        const { getSelect } = renderTimezoneSelect({ value: 'UTC', onChange })

        await userEvent.click(getSelect())

        // Verify the Local option is rendered in dropdown
        expect(screen.getByText(/^Local/)).toBeInTheDocument()
    })

    it('includes additional timezones when provided', async () => {
        const onChange = jest.fn()
        const { getSelect } = renderTimezoneSelect({
            value: 'UTC',
            onChange,
            additionalTimezones: ['America/New_York'],
        })

        await userEvent.click(getSelect())

        expect(screen.getByText('Common')).toBeInTheDocument()
        expect(screen.getByText('Other')).toBeInTheDocument()
        expect(screen.getByText(/America\/New_York/)).toBeInTheDocument()
    })

    it('does not duplicate project timezone if it matches UTC', async () => {
        const onChange = jest.fn()
        const { getSelect } = renderTimezoneSelect({ value: 'UTC', onChange })

        await userEvent.click(getSelect())

        // Should not have a "Project" option when project timezone is UTC
        expect(screen.queryByText(/^Project/)).not.toBeInTheDocument()
    })
})
