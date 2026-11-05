import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import '@testing-library/jest-dom'

import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { expectLogic } from 'kea-test-utils'
import { createElement } from 'react'

import { FEATURE_FLAGS, OrganizationMembershipLevel } from 'lib/constants'
import { integrationsLogic } from 'lib/integrations/integrationsLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { ChannelCatalog } from './ChannelCatalog'
import { channelCatalogLogic } from './channelCatalogLogic'
import { MessageChannels } from './MessageChannels'

describe('sandbox setup in the channel catalog', () => {
    let logic: ReturnType<typeof channelCatalogLogic.build>

    beforeEach(() => initKeaTests())
    afterEach(() => {
        cleanup()
        logic?.unmount()
    })

    it.each([404, 500])('starts setup on mount and recovers from a %s through Try again', async (failureStatus) => {
        let status = failureStatus
        let requests = 0
        const sandbox = {
            id: 9,
            kind: 'email',
            config: {
                provider: 'sandbox',
                verified: true,
                name: 'Acme via PostHog',
                email: 'hello@sandbox.example.com',
            },
        }
        useMocks({
            get: { '/api/projects/:team_id/integrations/': () => [200, { results: status === 200 ? [sandbox] : [] }] },
            post: {
                '/api/projects/:team_id/integrations/email_sandbox_sender/': () => {
                    requests++
                    return status === 200
                        ? [200, sandbox]
                        : [status, { detail: 'Could not set up your sandbox sender.' }]
                },
            },
        })
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
            [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
        })
        logic = channelCatalogLogic()
        logic.mount()
        await waitFor(() => expect(requests).toBe(1))
        await expectLogic(integrationsLogic).toFinishAllListeners()
        render(createElement(MessageChannels))
        expect(await screen.findByText('Could not set up your sandbox sender.')).toBeInTheDocument()

        status = 200
        fireEvent.click(screen.getAllByText('Try again')[0])
        expect(await screen.findByText('Acme via PostHog <hello@sandbox.example.com>')).toBeInTheDocument()
        expect(requests).toBe(2)
        expect(screen.queryByText('Could not set up your sandbox sender.')).not.toBeInTheDocument()
    })

    it('drops a failed setup once the sandbox flag turns off', async () => {
        useMocks({
            get: { '/api/projects/:team_id/integrations/': () => [200, { results: [] }] },
            post: {
                '/api/projects/:team_id/integrations/email_sandbox_sender/': () => [
                    500,
                    { detail: 'Could not set up your sandbox sender.' },
                ],
            },
        })
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
            [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
        })
        logic = channelCatalogLogic()
        logic.mount()
        await waitFor(() => expect(logic.values.sandboxSetupError).toBe('Could not set up your sandbox sender.'))

        featureFlagLogic.actions.setFeatureFlags([], {})

        expect(logic.values.sandboxSetupError).toBeNull()
    })

    it('keeps a channel load failure separate from sandbox setup', async () => {
        let loadStatus = 500
        const sandbox = { id: 9, kind: 'email', config: { provider: 'sandbox', verified: true } }
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () =>
                    loadStatus === 200
                        ? [200, { results: [sandbox] }]
                        : [500, { detail: 'Could not load your channels.' }],
            },
            post: { '/api/projects/:team_id/integrations/email_sandbox_sender/': [200, sandbox] },
        })
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
            [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
        })
        logic = channelCatalogLogic()
        logic.mount()
        await expectLogic(integrationsLogic).toDispatchActions(['loadIntegrationsFailure'])
        await expectLogic(integrationsLogic).toFinishAllListeners()
        expect(logic.values.channels).toBeNull()
        expect(logic.values.integrationsLoadFailed).toBe(true)
        expect(logic.values.sandboxSetupError).toBeNull()

        render(createElement(ChannelCatalog))
        expect(screen.getByText(/Couldn't load your channels/)).toBeInTheDocument()
        cleanup()

        loadStatus = 200
        await expectLogic(integrationsLogic, () => integrationsLogic.actions.loadIntegrations()).toFinishAllListeners()
        await expectLogic(integrationsLogic).toFinishAllListeners()
        expect(logic.values.integrationsLoadFailed).toBe(false)
        expect(logic.values.channels).not.toBeNull()
        expect(logic.values.sandboxSetupError).toBeNull()
        render(createElement(ChannelCatalog))
        expect(screen.getByTestId('workflows-channel-catalog-email')).toBeInTheDocument()
    })

    it('offers Try again when the refresh after setup fails over an earlier list', async () => {
        let loads = 0
        let refreshStatus = 500
        const sandbox = {
            id: 9,
            kind: 'email',
            config: {
                provider: 'sandbox',
                verified: true,
                name: 'Acme via PostHog',
                email: 'hello@sandbox.example.com',
            },
        }
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () => {
                    loads++
                    if (loads === 1) {
                        return [200, { results: [] }]
                    }
                    return refreshStatus === 200
                        ? [200, { results: [sandbox] }]
                        : [500, { detail: 'Could not load your channels.' }]
                },
            },
            post: { '/api/projects/:team_id/integrations/email_sandbox_sender/': [200, sandbox] },
        })
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
            [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
        })
        integrationsLogic.mount()
        await expectLogic(integrationsLogic).toDispatchActions(['loadIntegrationsSuccess'])
        logic = channelCatalogLogic()
        logic.mount()
        await expectLogic(integrationsLogic).toDispatchActions(['loadIntegrationsFailure'])
        await expectLogic(integrationsLogic).toFinishAllListeners()
        expect(logic.values.channels).not.toBeNull()
        render(createElement(MessageChannels))
        expect(await screen.findByText('Could not load the sandbox sender.')).toBeInTheDocument()

        refreshStatus = 200
        fireEvent.click(screen.getAllByText('Try again')[0])
        expect(await screen.findByText('Acme via PostHog <hello@sandbox.example.com>')).toBeInTheDocument()
        expect(screen.queryByText('Could not load the sandbox sender.')).not.toBeInTheDocument()
    })

    it('ignores a setup failure from an earlier visit after Channels opens again', async () => {
        let failFirstRequest: () => void = () => {}
        let requests = 0
        const sandbox = { id: 9, kind: 'email', config: { provider: 'sandbox', verified: true } }
        useMocks({
            get: { '/api/projects/:team_id/integrations/': () => [200, { results: requests > 1 ? [sandbox] : [] }] },
            post: {
                '/api/projects/:team_id/integrations/email_sandbox_sender/': () => {
                    requests++
                    if (requests > 1) {
                        return [200, sandbox]
                    }
                    return new Promise((resolve) => {
                        failFirstRequest = () => resolve([500, { detail: 'Could not set up your sandbox sender.' }])
                    })
                },
            },
        })
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
            [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
        })
        logic = channelCatalogLogic()
        logic.mount()
        await waitFor(() => expect(requests).toBe(1))
        logic.unmount()

        logic = channelCatalogLogic()
        logic.mount()
        await waitFor(() => expect(integrationsLogic.values.sandboxEmailSender).not.toBeNull())
        failFirstRequest()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests).toBe(2)
        expect(logic.values.sandboxSetupError).toBeNull()
    })

    it.each([
        { when: 'the flag is on at mount', flagAtMount: true, hasSender: false },
        { when: 'the flag arrives after mount', flagAtMount: false, hasSender: false },
        { when: 'the flag arrives after mount and the sender exists', flagAtMount: false, hasSender: true },
    ])('sets up the sandbox sender once when $when', async ({ flagAtMount, hasSender }) => {
        let requests = 0
        const sandbox = { id: 9, kind: 'email', config: { provider: 'sandbox', verified: true } }
        useMocks({
            get: {
                '/api/projects/:team_id/integrations/': () => [
                    200,
                    { results: hasSender || requests > 0 ? [sandbox] : [] },
                ],
            },
            post: {
                '/api/projects/:team_id/integrations/email_sandbox_sender/': () => {
                    requests++
                    return [200, sandbox]
                },
            },
        })
        const enableFlag = (): void =>
            featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
                [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
            })
        featureFlagLogic.actions.setFeatureFlags([], {})
        if (flagAtMount) {
            enableFlag()
        }
        logic = channelCatalogLogic()
        logic.mount()
        await expectLogic(integrationsLogic).toFinishAllListeners()
        expect(requests).toBe(flagAtMount ? 1 : 0)

        enableFlag()
        await waitFor(() => expect(integrationsLogic.values.sandboxEmailSender).not.toBeNull())
        await expectLogic(logic).toFinishAllListeners()
        expect(requests).toBe(1)
    })

    it.each([
        {
            who: 'a project member below admin',
            level: OrganizationMembershipLevel.Member,
            existing: [],
            status: 200,
        },
        {
            who: 'a project that already has the sender, so its name follows the organization',
            level: OrganizationMembershipLevel.Admin,
            existing: [9],
            status: 200,
        },
        {
            who: 'a project whose sender refresh fails, without an error over the working row',
            level: OrganizationMembershipLevel.Admin,
            existing: [9],
            status: 500,
        },
    ])('sends one setup request on mount for $who', async ({ level, existing, status }) => {
        let requests = 0
        const results = existing.map((id) => ({ id, kind: 'email', config: { provider: 'sandbox', verified: true } }))
        useMocks({
            get: { '/api/projects/:team_id/integrations/': () => [200, { results }] },
            post: {
                '/api/projects/:team_id/integrations/email_sandbox_sender/': () => {
                    requests++
                    return status === 200
                        ? [200, { id: 9, kind: 'email', config: { provider: 'sandbox', verified: true } }]
                        : [status, { detail: 'Server error' }]
                },
            },
        })
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, effective_membership_level: level })
        featureFlagLogic.actions.setFeatureFlags([FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER], {
            [FEATURE_FLAGS.WORKFLOWS_SANDBOX_SENDER]: true,
        })
        integrationsLogic.mount()
        await expectLogic(integrationsLogic).toFinishAllListeners()

        logic = channelCatalogLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(requests).toBe(1)
        expect(logic.values.sandboxSetupError).toBeNull()
    })
})
