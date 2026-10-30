import '@testing-library/jest-dom'

import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

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
        })
        // The roster only loads its sources behind this flag, so without it every list stays empty.
        featureFlagLogic.mount()
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.PRODUCT_AUTONOMY], {
            [FEATURE_FLAGS.PRODUCT_AUTONOMY]: true,
        })
    })
    afterEach(cleanup)

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
