import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { expectLogic } from 'kea-test-utils'

import { teamLogic } from 'scenes/teamLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { sandboxSenderLogic } from './sandboxSenderLogic'

describe('sandboxSenderLogic', () => {
    it('reads and sets up the sandbox sender in the selected environment rather than its project', async () => {
        const environmentId = MOCK_DEFAULT_TEAM.id + 1
        const requestedIds: string[] = []
        initKeaTests()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, id: environmentId })
        useMocks({
            get: {
                '/api/projects/:team_id/workflow_email_sandbox/status/': (req: any) => {
                    requestedIds.push(String(req.params.team_id))
                    return [
                        200,
                        {
                            integration_id: null,
                            from_address: 'sandbox@example.com',
                            display_name: 'Example via PostHog',
                            organization_blocked: false,
                            adoption_enabled: true,
                        },
                    ]
                },
            },
            post: {
                '/api/projects/:team_id/workflow_email_sandbox/provision/': (req: any) => {
                    requestedIds.push(String(req.params.team_id))
                    return [200, { integration_id: 11 }]
                },
            },
        })
        const logic = sandboxSenderLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSandboxStatusSuccess'])

        logic.actions.provisionSandboxSender('channels')
        await expectLogic(logic).toDispatchActions(['setSandboxIntegrationId'])

        expect(requestedIds).toEqual([String(environmentId), String(environmentId)])
        expect(logic.values.sandboxStatus?.integration_id).toEqual(11)
        logic.unmount()
    })

    it.each([
        [
            'the sender was never set up',
            {},
            'not attempted',
            { problem: "The sandbox sender isn't set up for this project yet.", canSetUp: true },
        ],
        [
            'the sender is being set up',
            {},
            'in flight',
            { problem: "The sandbox sender isn't set up for this project yet.", canSetUp: true },
        ],
        [
            'setting up the sender failed',
            {},
            'fails',
            { problem: "This organization can't use the sandbox sender.", canSetUp: true },
        ],
        ['setting up the sender succeeded', {}, 'succeeds', null],
        [
            'the organization is blocked',
            { organization_blocked: true },
            'not attempted',
            { problem: 'Sandbox email is turned off for your organization. Choose your own sender.', canSetUp: false },
        ],
        [
            'the organization is blocked after the sender was set up',
            { integration_id: 11, organization_blocked: true },
            'not attempted',
            { problem: 'Sandbox email is turned off for your organization. Choose your own sender.', canSetUp: false },
        ],
        [
            'the project cannot adopt the sender',
            { adoption_enabled: false },
            'not attempted',
            {
                problem: "The sandbox sender isn't available for this project. Choose your own sender.",
                canSetUp: false,
            },
        ],
    ])('tells a sandbox step when %s', async (_, statusOverrides, provisioning, expectedSetup) => {
        initKeaTests()
        useMocks({
            get: {
                '/api/projects/:team_id/workflow_email_sandbox/status/': {
                    integration_id: null,
                    from_address: 'sandbox@example.com',
                    display_name: 'Example via PostHog',
                    organization_blocked: false,
                    adoption_enabled: true,
                    ...statusOverrides,
                },
            },
            post: {
                '/api/projects/:team_id/workflow_email_sandbox/provision/': async () => {
                    if (provisioning === 'in flight') {
                        await new Promise(() => {})
                    }
                    return provisioning === 'fails'
                        ? [403, { detail: "This organization can't use the sandbox sender." }]
                        : [200, { integration_id: 11 }]
                },
            },
        })
        const logic = sandboxSenderLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSandboxStatusSuccess'])

        if (provisioning === 'in flight') {
            logic.actions.provisionSandboxSender('sender_control')
        } else if (provisioning !== 'not attempted') {
            logic.actions.provisionSandboxSender('sender_control')
            await expectLogic(logic).toFinishAllListeners()
        }

        expect(logic.values.sandboxSetup).toEqual(expectedSetup)
        logic.unmount()
    })
})
