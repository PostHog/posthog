/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import '@testing-library/jest-dom'

import { act, cleanup, render, screen, waitFor } from '@testing-library/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { wizardActiveSessionDetectorLogic } from 'scenes/onboarding/shared/wizard-sync/wizardActiveSessionDetectorLogic'
import { SELF_DRIVING_WORKFLOW_ID } from 'scenes/onboarding/shared/wizard-sync/workflows'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { mockSourceConfigs } from '../../__mocks__/inboxMocks'
import { inboxOnboardingLogic } from '../../logics/inboxOnboardingLogic'
import { InboxWaitingForWork } from './InboxWaitingForWork'

jest.mock('posthog-js')

function mockWatchers(sourceConfigs: unknown[], reportCount: number = 0): void {
    useMocks({
        get: {
            '/api/environments/:team_id/external_data_sources/': () => [
                200,
                { results: [], count: 0, next: null, previous: null },
            ],
            '/api/projects/:team_id/signals/reports/': () => [
                200,
                { count: reportCount, next: null, previous: null, results: [] },
            ],
            '/api/projects/:team_id/signals/reports/available_reviewers': {},
            '/api/projects/:team_id/signals/source_configs/': () => [
                200,
                { results: sourceConfigs, count: sourceConfigs.length, next: null, previous: null },
            ],
            '/api/projects/:team_id/signals/scout/configs/': () => [200, []],
            '/api/projects/:team_id/vision/scanners/': () => [
                200,
                { results: [], count: 0, next: null, previous: null },
            ],
        },
    })
}

describe('InboxWaitingForWork', () => {
    beforeEach(() => {
        initKeaTests()
        // The source-config and Vision-scanner loads are gated on this flag, and the setup verdict
        // never settles without them.
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_AUTONOMY], {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
        })
    })

    afterEach(cleanup)

    // The screen promised that agents were working on a project where nothing was enabled, so a
    // setup run that ended without turning anything on read as "wait longer" forever.
    it('offers a way to finish setup when nothing is watching', async () => {
        mockWatchers([])

        render(<InboxWaitingForWork />)

        await waitFor(() => expect(screen.getByText("Setup isn't finished")).toBeInTheDocument())
        expect(screen.queryByText('Your agents are working in the background')).toBeNull()
        expect(screen.getByText('Turn on sources')).toBeInTheDocument()
        expect(screen.getByText('Browse scouts')).toBeInTheDocument()
    })

    it('keeps the waiting state once something is watching', async () => {
        mockWatchers(mockSourceConfigs.results)

        render(<InboxWaitingForWork />)

        await waitFor(() => expect(screen.getByText('Your agents are working in the background')).toBeInTheDocument())
        expect(screen.queryByText("Setup isn't finished")).toBeNull()
    })

    // Before the detector reports, "no run in flight" is only "nobody has asked yet", so a user
    // whose setup run is under way was told to go and run it again.
    it('waits for the wizard verdict before saying setup is unfinished', async () => {
        // The detector only watches the setup program on this variant, so its verdict is the one
        // thing the surface is waiting on. The failing poll keeps it from reaching one.
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_AUTONOMY], {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
            [FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]: 'self-driving',
        })
        mockWatchers([])
        useMocks({ get: { '/api/projects/:project_id/wizard/sessions/latest/': () => [500, {}] } })

        render(<InboxWaitingForWork />)

        await waitFor(() => expect(screen.getByText('Your agents are working in the background')).toBeInTheDocument())
        expect(screen.queryByText("Setup isn't finished")).toBeNull()

        act(() => {
            wizardActiveSessionDetectorLogic.actions.markInactive()
        })

        await waitFor(() => expect(screen.getByText("Setup isn't finished")).toBeInTheDocument())
    })

    // A run that ends refetches every config, and the loaded ones hold their pre-run values until
    // the fresh ones land, so the surface used to greet a finished run with "run it again".
    it('waits for the refetched configs when a run ends', async () => {
        mockWatchers([])

        render(<InboxWaitingForWork />)

        await waitFor(() => expect(screen.getByText("Setup isn't finished")).toBeInTheDocument())

        act(() => {
            wizardActiveSessionDetectorLogic.actions.markActive(SELF_DRIVING_WORKFLOW_ID)
        })
        expect(screen.getByText('Your agents are working in the background')).toBeInTheDocument()

        act(() => {
            wizardActiveSessionDetectorLogic.actions.markInactive()
        })
        expect(screen.queryByText("Setup isn't finished")).toBeNull()

        await waitFor(() => expect(screen.getByText("Setup isn't finished")).toBeInTheDocument())
    })

    // An empty legacy Pull requests tab can sit under the scene's paused banner while reports wait
    // on another tab. A second prompt there contradicted the banner and outlived its dismissal.
    it('leaves the setup prompt to the banner when work waits on another tab', async () => {
        mockWatchers([], 3)

        render(<InboxWaitingForWork />)

        await waitFor(() => expect(inboxOnboardingLogic.values.hasExistingWork).toBe(true))
        await waitFor(() => expect(screen.getByText('No signal sources are active.')).toBeInTheDocument())
        expect(screen.queryByText("Setup isn't finished")).toBeNull()
    })
})
