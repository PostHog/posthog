import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { SeverityLevelsFilter } from './SeverityLevelsFilter'

describe('SeverityLevelsFilter', () => {
    afterEach(cleanup)

    it('selects every severity level from the alert bulk action', () => {
        const onChange = jest.fn()
        render(<SeverityLevelsFilter value={['error']} onChange={onChange} showBulkActions />)

        fireEvent.click(screen.getByTestId('logs-severity-filter'))
        fireEvent.click(screen.getByTestId('logs-severity-select-all'))

        expect(onChange).toHaveBeenCalledWith(['trace', 'debug', 'info', 'warn', 'error', 'fatal'])
    })

    it('clears every severity level from the alert bulk action', () => {
        const onChange = jest.fn()
        render(
            <SeverityLevelsFilter
                value={['trace', 'debug', 'info', 'warn', 'error', 'fatal']}
                onChange={onChange}
                showBulkActions
            />
        )

        fireEvent.click(screen.getByTestId('logs-severity-filter'))
        fireEvent.click(screen.getByTestId('logs-severity-clear-all'))

        expect(onChange).toHaveBeenCalledWith([])
    })
})
