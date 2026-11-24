import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { broadcastWizardLogic } from '../broadcastWizardLogic'
import { BroadcastContentStep } from './BroadcastContentStep'

describe('BroadcastContentStep', () => {
    beforeEach(() => {
        useMocks({
            get: {
                '/api/environments/:team_id/integrations': { results: [] },
                '/api/projects/:team_id/integrations': { results: [] },
            },
        })
        initKeaTests()
    })

    afterEach(() => {
        cleanup()
    })

    it.each([
        { trackingEnabled: true, shown: /are connected to the sessions they start/, hidden: /Links stay as written/ },
        { trackingEnabled: false, shown: /Links stay as written/, hidden: /are connected to the sessions they start/ },
    ])('with tracking $trackingEnabled shows $shown', async ({ trackingEnabled, shown, hidden }) => {
        const wizard = broadcastWizardLogic({ id: 'new' })
        wizard.mount()
        wizard.actions.setEmailSettings({ trackingEnabled })

        render(
            <BindLogic logic={broadcastWizardLogic} props={{ id: 'new' }}>
                <BroadcastContentStep />
            </BindLogic>
        )

        expect(await screen.findByText(shown)).toBeInTheDocument()
        expect(screen.queryByText(hidden)).not.toBeInTheDocument()
    })
})
