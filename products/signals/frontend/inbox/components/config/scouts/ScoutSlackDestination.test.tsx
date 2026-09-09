import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen } from '@testing-library/react'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import type { IntegrationType } from '~/types'

import type { SignalScoutSlackDestinationApi } from 'products/signals/frontend/generated/api.schemas'

import { ScoutSlackDestination } from './ScoutSlackDestination'

const SLACK_WORKSPACE = { id: 1, kind: 'slack', display_name: 'PostHog' } as IntegrationType
const BROKEN_WORKSPACE = { ...SLACK_WORKSPACE, errors: 'TOKEN_REFRESH_FAILED' } as IntegrationType

describe('ScoutSlackDestination', () => {
    let workspaces: IntegrationType[] = []

    beforeEach(() => {
        initKeaTests()
        workspaces = [SLACK_WORKSPACE]
        // msw handlers reset between tests, so register per test rather than once per file.
        useMocks({
            get: {
                '/api/environments/:team_id/integrations/': () => [200, { results: workspaces }],
            },
        })
    })
    afterEach(cleanup)

    // The header is all most people read, so it has to name the target the next run actually posts
    // to. Reading "Off" or "Not connected" over a live destination would hide a scout that is
    // already posting into a channel.
    it.each([
        ['a channel', { integration_id: 1, channel: 'C123|#alerts' }, true, ['#alerts'], ['Threaded', 'Disconnected']],
        [
            'a threaded channel',
            { integration_id: 1, channel: 'C123|#alerts', thread_reports: true },
            true,
            ['#alerts', 'Threaded'],
            [],
        ],
        // A channel saved through the API carries no name, and the opaque id names nothing a
        // reader recognizes.
        ['a bare channel id', { integration_id: 1, channel: 'C0123ABC456' }, true, ['Slack channel'], ['C0123ABC456']],
        ['several DM recipients', { integration_id: 1, users: ['U1|@ana', 'U2|@bo'] }, true, ['DM to 2 people'], []],
        ['a single DM recipient', { integration_id: 1, users: ['U1|@ana'] }, true, ['DM to 1 person'], []],
        // The harness threads each direct message too, so a header that reported threading only
        // for channels would hide how the report arrives.
        [
            'threaded direct messages',
            { integration_id: 1, users: ['U1|@ana'], thread_reports: true },
            true,
            ['DM to 1 person', 'Threaded'],
            [],
        ],
        // Delivery fails on every run once the workspace behind a saved destination is gone, so a
        // header that still read as a live channel would hide a scout that posts nowhere.
        [
            'a destination whose workspace was disconnected',
            { integration_id: 99, channel: 'C123|#alerts' },
            true,
            ['#alerts', 'Disconnected'],
            [],
        ],
        ['no destination', undefined, true, ['Off'], []],
        ['no Slack workspace', undefined, false, ['Not connected'], []],
    ])(
        'summarizes %s in the header, with the section closed',
        async (
            _name,
            destination: SignalScoutSlackDestinationApi | undefined,
            connected: boolean,
            expected: string[],
            unexpected: string[]
        ) => {
            workspaces = connected ? [SLACK_WORKSPACE] : []

            render(<ScoutSlackDestination destination={destination} onChange={jest.fn()} />)

            for (const text of expected) {
                expect(await screen.findByText(text)).toBeInTheDocument()
            }
            for (const text of unexpected) {
                expect(screen.queryByText(text)).not.toBeInTheDocument()
            }
            expect(screen.queryByText(/Post each scout run/)).not.toBeInTheDocument()
        }
    )

    // The picker's health checks only run once the panel opens, so without this a workspace whose
    // token was revoked reads as a live channel and every run silently fails to deliver.
    it('reports a workspace that can no longer authenticate, with the section closed', async () => {
        workspaces = [BROKEN_WORKSPACE]

        render(
            <ScoutSlackDestination destination={{ integration_id: 1, channel: 'C123|#alerts' }} onChange={jest.fn()} />
        )

        expect(await screen.findByText('Reconnect')).toBeInTheDocument()
        expect(screen.getByText('#alerts')).toBeInTheDocument()
        expect(screen.queryByText('Disconnected')).not.toBeInTheDocument()
    })

    it('opens the picker from the header', async () => {
        render(<ScoutSlackDestination destination={undefined} onChange={jest.fn()} />)

        fireEvent.click(await screen.findByText('Slack destination'))

        expect(await screen.findByText(/Post each scout run/)).toBeInTheDocument()
        expect(screen.getByText('Direct message')).toBeInTheDocument()
    })
})
