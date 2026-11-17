import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import { initKeaTests } from '~/test/init'

import { BroadcastTrackingSwitch } from './BroadcastTrackingSwitch'

function StatefulSwitch(): JSX.Element {
    const [checked, setChecked] = useState(true)
    return <BroadcastTrackingSwitch checked={checked} onChange={setChecked} />
}

describe('<BroadcastTrackingSwitch />', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('shows the run link tag hint only while tracking is on', () => {
        const { container } = render(<StatefulSwitch />)
        expect(screen.getByText(/are connected to the sessions they start/)).toBeInTheDocument()

        fireEvent.click(container.querySelector('[data-attr="broadcast-tracking-toggle"]') as HTMLElement)

        expect(screen.queryByText(/connected to sessions/)).not.toBeInTheDocument()
        expect(screen.getByText(/Links stay as written/)).toBeInTheDocument()
    })
})
