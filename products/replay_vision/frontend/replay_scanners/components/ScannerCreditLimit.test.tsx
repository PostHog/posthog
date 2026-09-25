import '@testing-library/jest-dom'

import { fireEvent, render, screen } from '@testing-library/react'
import { Form } from 'kea-forms'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { replayScannerLogic } from '../replayScannerLogic'
import { ScannerCreditLimit } from './ScannerCreditLimit'

describe('ScannerCreditLimit', () => {
    let logic: ReturnType<typeof replayScannerLogic.build>

    beforeEach(() => {
        useMocks({ get: { '/api/projects/:team/vision/scanners/:id/': () => [404, {}] } })
        localStorage.clear()
        initKeaTests()
        logic = replayScannerLogic({ id: 'new' })
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('toggles the limit on when the description next to the switch is clicked', () => {
        render(
            <Form logic={replayScannerLogic} props={{ id: 'new' }} formKey="scanner">
                <ScannerCreditLimit scannerId="new" />
            </Form>
        )
        expect(logic.values.scanner.credit_limit_enabled).toBeFalsy()

        fireEvent.click(
            screen.getByText("Cap what this scanner spends in a billing period, on top of your organization's limit.")
        )

        expect(logic.values.scanner.credit_limit_enabled).toBe(true)
    })
})
