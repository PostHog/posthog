import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { Provider } from 'kea'

import { initKeaTests } from '~/test/init'

import { transactionalEmailWizardLogic } from '../transactionalEmailWizardLogic'
import { NameStep } from './NameStep'

describe('NameStep', () => {
    afterEach(() => {
        cleanup()
    })

    it('reveals Track link clicks only while Protect sensitive data is on and resets it when turned off', () => {
        initKeaTests()
        const logic = transactionalEmailWizardLogic()
        logic.mount()

        render(
            <Provider>
                <NameStep />
            </Provider>
        )

        expect(screen.queryByLabelText('Track link clicks')).not.toBeInTheDocument()

        const sensitiveToggle = screen.getByLabelText('Protect sensitive data')
        fireEvent.click(sensitiveToggle)

        const clickToggle = screen.getByLabelText('Track link clicks')
        expect(clickToggle).toHaveAttribute('aria-checked', 'false')

        fireEvent.click(clickToggle)
        expect(clickToggle).toHaveAttribute('aria-checked', 'true')

        fireEvent.click(sensitiveToggle)
        expect(screen.queryByLabelText('Track link clicks')).not.toBeInTheDocument()

        fireEvent.click(sensitiveToggle)
        expect(screen.getByLabelText('Track link clicks')).toHaveAttribute('aria-checked', 'false')

        logic.unmount()
    })
})
