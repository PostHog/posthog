import '@testing-library/jest-dom'

import { cleanup, render, screen } from '@testing-library/react'
import { BindLogic } from 'kea'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlowApi } from 'products/workflows/frontend/generated/api.schemas'

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
        {
            trackingEnabled: true,
            sensitive: false,
            shown: /Connect clicks to sessions/,
            hidden: /Links stay as written/,
        },
        {
            trackingEnabled: false,
            sensitive: false,
            shown: /Links stay as written/,
            hidden: /Connect clicks to sessions/,
        },
        {
            trackingEnabled: true,
            sensitive: true,
            shown: /Track opens and link clicks/,
            hidden: /Connect clicks to sessions/,
        },
    ])(
        'with tracking $trackingEnabled and sensitive $sensitive shows $shown',
        async ({ trackingEnabled, sensitive, shown, hidden }) => {
            const wizard = broadcastWizardLogic({ id: 'new' })
            wizard.mount()
            wizard.actions.setEmailSettings({ trackingEnabled })
            if (sensitive) {
                wizard.actions.draftAutosaved({
                    id: 'broadcast-1',
                    status: 'draft',
                    actions: [{ id: 'email', type: 'function_email', config: { sensitive: true } }],
                } as unknown as HogFlowApi)
            }

            render(
                <BindLogic logic={broadcastWizardLogic} props={{ id: 'new' }}>
                    <BroadcastContentStep />
                </BindLogic>
            )

            expect(await screen.findByText(shown)).toBeInTheDocument()
            expect(screen.queryByText(hidden)).not.toBeInTheDocument()
        }
    )
})
