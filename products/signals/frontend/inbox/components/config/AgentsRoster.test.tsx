import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { signalTeamConfigLogic } from '../../logics/signalTeamConfigLogic'
import { signalSourcesLogic } from '../../signalSourcesLogic'
import { SourcesTab } from '../tabs/SourcesTab'
import { AgentsRoster } from './AgentsRoster'

const SCANNERS = Array.from({ length: 10 }, (_, index) => ({
    id: `scanner-${index}`,
    name: `Scanner ${index}`,
    description: `Watches step ${index}.`,
    scanner_type: 'monitor',
    enabled: true,
    emits_signals: false,
}))

const EMPTY_LIST = { count: 0, next: null, previous: null, results: [] }

const GITLAB_WIZARD_CONFIG = {
    name: 'GitLab',
    label: 'GitLab',
    iconPath: '/static/services/gitlab.svg',
    caption: null,
    supportsColumnSelection: false,
    versions: [],
    defaultVersion: '',
    deprecatedVersions: [],
    fields: [{ name: 'personal_access_token', label: 'Personal access token', type: 'password', required: true }],
}

const JIRA_SOURCE = {
    id: 'source-jira',
    source_type: 'Jira',
    status: 'Completed',
    schemas: [{ id: 'schema-jira', name: 'issues', should_sync: true, sync_type: 'full_refresh' }],
}

describe('AgentsRoster', () => {
    beforeEach(() => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_spend/': () => [200, []],
                '/api/projects/:team_id/signals/source_configs/': () => [200, { results: [] }],
                '/api/projects/:team_id/vision/scanners/': () => [
                    200,
                    { count: SCANNERS.length, next: null, previous: null, results: SCANNERS },
                ],
                '/api/projects/:team_id/event_definitions/': () => [200, EMPTY_LIST],
                '/api/environments/:team_id/external_data_sources/': () => [200, EMPTY_LIST],
                '/api/environments/:team_id/integrations/': () => [200, EMPTY_LIST],
                '/api/projects/:team_id/external_data_sources/wizard/': () => [200, { GitLab: GITLAB_WIZARD_CONFIG }],
            },
            post: {
                '/api/projects/:team_id/signals/source_configs/alert_pattern_preview/': () => [
                    200,
                    { alert_allow_patterns_error: null, alert_block_patterns_error: null, alerts: [], has_more: false },
                ],
            },
        })
        // The roster only loads its sources behind this flag, so without it every list stays empty.
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_AUTONOMY], {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
        })
    })
    afterEach(cleanup)

    it.each([
        { enabled: true, armed: true },
        { enabled: true, armed: false },
        { enabled: false, armed: true },
    ])('gates source usage when enabled=$enabled and armed=$armed', async ({ enabled, armed }) => {
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_AUTONOMY], {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
            [FEATURE_FLAGS.SELF_DRIVING_USAGE_DISPLAY]: enabled,
        })
        const usageRequests = jest.fn()
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': {
                    results: ['issue_created', 'issue_reopened', 'issue_spiking'].map((source_type) => ({
                        id: source_type,
                        source_product: 'error_tracking',
                        source_type,
                        enabled: armed,
                        config: {},
                    })),
                },
                '/api/projects/:team_id/signals/source_spend/': () => {
                    usageRequests()
                    return [
                        200,
                        [
                            {
                                source_product: 'error_tracking',
                                source_type: 'issue_created',
                                signal_count: 1,
                                spend: { total_spend: 125, incomplete: false },
                            },
                            {
                                source_product: 'error_tracking',
                                source_type: 'issue_spiking',
                                signal_count: 1,
                                spend: { total_spend: 25, incomplete: false },
                            },
                            {
                                source_product: 'conversations',
                                source_type: 'ticket',
                                signal_count: 1,
                                spend: { total_spend: null, incomplete: true },
                            },
                        ],
                    ]
                },
            },
        })
        render(<AgentsRoster />)
        const errorTracking = document.querySelector('[data-source="error_tracking"]') as HTMLElement
        expect(await within(errorTracking).findByLabelText('Arm Error tracking')).toBeInTheDocument()
        if (enabled && armed) {
            expect(await within(errorTracking).findByText('150 credits')).toBeInTheDocument()
            const support = document.querySelector('[data-source="conversations"]') as HTMLElement
            expect(within(support).queryByText('Not tracked')).not.toBeInTheDocument()
            expect(usageRequests).toHaveBeenCalledTimes(1)
        } else {
            expect(document.querySelector('[data-attr="source-spend"]')).toBeNull()
            expect(usageRequests).not.toHaveBeenCalled()
        }
    })

    it('keeps connected sources in the roster and connects from the inline catalog without losing the search', async () => {
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/': () => [
                    200,
                    { count: 1, next: null, previous: null, results: [JIRA_SOURCE] },
                ],
            },
        })
        render(<SourcesTab />)

        const jiraToggle = await screen.findByLabelText('Turn on Jira')
        expect(jiraToggle.closest('[data-attr="signal-source-row"]')).toHaveAttribute('data-source', 'jira')
        expect(document.querySelector('[data-attr="signal-source-row"][data-source="github"]')).toBeNull()
        expect(screen.getByText('Available sources')).toBeInTheDocument()
        expect(screen.queryByText('Add source')).not.toBeInTheDocument()
        const jiraTile = (): Element | null =>
            document.querySelector('[data-attr="signal-source-catalog-tile"][data-source="jira"]')
        await screen.findByLabelText('Connect GitLab')
        expect(jiraTile()).not.toBeInTheDocument()
        await userEvent.type(screen.getByLabelText('Search sources'), 'GitLab')
        expect(jiraTile()).toBeNull()

        await userEvent.click(await screen.findByLabelText('Connect GitLab'))
        expect(signalSourcesLogic.values.dataSourceSetupSource).toBe('gitlab')
        expect(await screen.findByText('Connect GitLab')).toBeInTheDocument()
        await userEvent.click(screen.getByText('Cancel'))
        expect(signalSourcesLogic.values.dataSourceSetupSource).toBeNull()
        expect(screen.getByLabelText('Search sources')).toHaveValue('GitLab')
        expect(screen.getByLabelText('Connect GitLab')).toBeInTheDocument()
    })

    it('lets a connection retry finish before another retry can start', async () => {
        let resolveRequest!: () => void
        const pendingRequest = new Promise<void>((resolve) => {
            resolveRequest = resolve
        })
        let requests = 0
        useMocks({
            get: {
                '/api/environments/:team_id/external_data_sources/': async () => {
                    requests++
                    if (requests === 1) {
                        return [500, { detail: 'Server error' }]
                    }
                    await pendingRequest
                    return [200, EMPTY_LIST]
                },
            },
        })
        render(<SourcesTab />)
        const retry = (await screen.findAllByText('Retry'))[0].closest('button')!
        await userEvent.click(retry)
        expect(retry).toHaveAttribute('aria-disabled', 'true')
        expect(screen.queryByLabelText('Connect GitLab')).not.toBeInTheDocument()
        expect(screen.queryByText(/All available sources are connected/)).not.toBeInTheDocument()
        resolveRequest()
        await waitFor(() => expect(screen.queryByText(/Couldn't load your connections/)).not.toBeInTheDocument())
        expect(await screen.findByLabelText('Connect GitLab')).toBeInTheDocument()
        expect(requests).toBe(2)
    })

    // The cap keeps a long user-created list from burying the sources below it, but a filter that
    // could not reach past it would make a scanner unfindable by name.
    it.each([
        {
            allFiringFlag: false,
            stored: 'all_firing_alerts',
            checked: 'Investigated alerts only',
            allFiringShown: false,
        },
        { allFiringFlag: true, stored: 'all_firing_alerts', checked: 'All firing alerts', allFiringShown: true },
        { allFiringFlag: false, stored: 'off', checked: 'Off', allFiringShown: false },
    ])(
        'shows alert scope $checked for stored $stored when the all alerts flag is $allFiringFlag',
        async ({ allFiringFlag, stored, checked, allFiringShown }) => {
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_AUTONOMY], {
                [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
                [FEATURE_FLAGS.SIGNALS_ANALYTICS_ALL_ALERTS]: allFiringFlag,
            })
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/source_configs/': {
                        results: [
                            {
                                id: 'analytics',
                                source_product: 'analytics',
                                source_type: 'anomaly_investigation',
                                enabled: true,
                                config: { alert_scope: stored },
                            },
                        ],
                    },
                },
            })
            render(<AgentsRoster />)

            const [expandButton] = await screen.findAllByLabelText('Expand Product analytics')
            await userEvent.click(expandButton)

            expect(await screen.findByLabelText(/^Off/)).toBeInTheDocument()
            expect(screen.getByLabelText(new RegExp(`^${checked}`))).toBeChecked()
            expect(screen.queryAllByLabelText(/^All firing alerts/)).toHaveLength(allFiringShown ? 1 : 0)
        }
    )

    // `anomaly_scoring_available` ignores the source state, so the roster has to gate the switch on it.
    it.each([
        { armed: true, available: true, shown: true },
        { armed: false, available: true, shown: false },
        { armed: true, available: false, shown: false },
    ])(
        'shows the anomaly scoring switch=$shown when the source is armed=$armed and scoring is available=$available',
        async ({ armed, available, shown }) => {
            const patches: Record<string, unknown>[] = []
            useMocks({
                get: {
                    '/api/projects/:team_id/signals/source_configs/': {
                        results: [
                            {
                                id: 'analytics',
                                source_product: 'analytics',
                                source_type: 'anomaly_investigation',
                                enabled: armed,
                                config: {},
                            },
                        ],
                    },
                    '/api/projects/:team_id/signals/config/': () => [
                        200,
                        { anomaly_scoring_enabled: true, anomaly_scoring_available: available },
                    ],
                },
                post: {
                    '/api/projects/:team_id/signals/config/': async ({ request }) => {
                        const patch = (await request.json()) as Record<string, unknown>
                        patches.push(patch)
                        return [200, { anomaly_scoring_available: available, ...patch }]
                    },
                },
            })
            render(<AgentsRoster />)
            await waitFor(() => expect(signalTeamConfigLogic.values.teamConfig).not.toBeNull())

            const [expandButton] = await screen.findAllByLabelText('Expand Product analytics')
            await userEvent.click(expandButton)
            expect(await screen.findByText('Alerts that become signals')).toBeInTheDocument()

            const scoringSwitch = (): HTMLElement | null =>
                screen.queryByLabelText('Score active trends insights for anomalies')
            if (!shown) {
                expect(scoringSwitch()).not.toBeInTheDocument()
                return
            }
            await waitFor(() => expect(scoringSwitch()).toBeChecked())
            await userEvent.click(scoringSwitch()!)
            await waitFor(() => expect(patches).toEqual([{ anomaly_scoring_enabled: false }]))
            await waitFor(() => expect(scoringSwitch()).not.toBeChecked())
        }
    )

    it('caps the scanner list, and lets both the filter and Show more reach past the cap', async () => {
        render(<AgentsRoster />)
        await userEvent.click(await screen.findByText('Replay vision'))

        expect(await screen.findByText('Scanner 7')).toBeInTheDocument()
        expect(screen.queryByText('Scanner 8')).not.toBeInTheDocument()

        await userEvent.type(screen.getByPlaceholderText('Filter scanners'), 'Scanner 9')
        expect(await screen.findByText('Scanner 9')).toBeInTheDocument()

        await userEvent.clear(screen.getByPlaceholderText('Filter scanners'))
        await userEvent.click(await screen.findByText('Show 2 more scanners'))
        expect(await screen.findByText('Scanner 9')).toBeInTheDocument()
    })

    // A failed load leaves every switch reading off and every import source reading unconnected.
    // A click then creates a row that may already exist, so the switches and tiles have to stay shut.
    it('holds the source switches and catalog shut while the source list has failed to load', async () => {
        useMocks({
            get: {
                '/api/projects/:team_id/signals/source_configs/': () => [500, { detail: 'Server error' }],
            },
        })
        render(<SourcesTab />)

        expect(await screen.findByText(/Couldn't load your signal sources/)).toBeInTheDocument()
        expect(screen.getByLabelText('Arm Support')).toBeDisabled()
        expect(await screen.findByText(/Couldn't load available sources/)).toBeInTheDocument()
        expect(screen.queryByLabelText('Connect GitHub issues')).not.toBeInTheDocument()
        expect(signalSourcesLogic.values.dataSourceSetupSource).toBeNull()
    })
})
