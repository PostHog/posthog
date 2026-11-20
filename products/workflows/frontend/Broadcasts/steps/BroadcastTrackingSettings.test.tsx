import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'

import { initKeaTests } from '~/test/init'

import { BroadcastTrackingSettings } from './BroadcastTrackingSettings'

function StatefulSettings(): JSX.Element {
    const [settings, setSettings] = useState({ trackingEnabled: true, utmTagsEnabled: false })
    return (
        <BroadcastTrackingSettings
            {...settings}
            onChange={(changed) => setSettings((current) => ({ ...current, ...changed }))}
        />
    )
}

describe('<BroadcastTrackingSettings />', () => {
    beforeEach(() => {
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it('keeps both switches in one row and shows the run link tag hint only while tracking is on', () => {
        const { container } = render(<StatefulSettings />)
        const row = container.querySelector('[data-attr="broadcast-tracking-settings"]') as HTMLElement
        const trackingToggle = container.querySelector('[data-attr="broadcast-tracking-toggle"]') as HTMLElement
        const hint = container.querySelector('[data-attr="workflows-run-link-tag-hint"]') as HTMLElement

        expect(row).toContainElement(trackingToggle)
        expect(row).toContainElement(container.querySelector('[data-attr="broadcast-utm-tags-toggle"]'))
        expect(row).not.toContainElement(hint)
        expect(screen.getByText(/are connected to the sessions they start/)).toBeInTheDocument()

        fireEvent.click(trackingToggle)

        expect(container.querySelector('[data-attr="workflows-run-link-tag-hint"]')).not.toBeInTheDocument()
        expect(screen.getByText(/Links stay as written/)).toBeInTheDocument()
    })
})
