import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

import { initKeaTests } from '~/test/init'

import { tracingOtlpSetupLogic } from './tracingOtlpSetupLogic'
import { TracingSetupPlatform } from './tracingOtlpSnippets'

describe('tracingOtlpSetupLogic', () => {
    let logic: ReturnType<typeof tracingOtlpSetupLogic.build>

    beforeEach(() => {
        initKeaTests()
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, api_token: 'phc_test_token' })
        logic = tracingOtlpSetupLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
    })

    test.each<[TracingSetupPlatform, string]>([
        ['sdk', 'deployment.environment.name=staging'],
        ['docker', 'deployment.environment.name=staging'],
        ['kubernetes', 'deployment.environment.name=staging'],
        ['collector', 'value: "staging"'],
    ])('fills the token and traces endpoint, and writes the environment, for %s', (platform, environmentLine) => {
        logic.actions.setPlatform(platform)
        expect(logic.values.snippet).toContain('phc_test_token')
        expect(logic.values.snippet).toContain(`${window.location.origin}/i/v1/traces`)
        expect(logic.values.snippet).not.toContain('deployment.environment')

        logic.actions.setEnvironment('staging')
        expect(logic.values.snippet).toContain(environmentLine)
    })

    it('keeps characters that would break the snippet out of the environment', () => {
        logic.actions.setEnvironment('prod eu,"x=1"')
        expect(logic.values.environment).toEqual('prod-eux1')
        expect(logic.values.snippet).toContain('OTEL_RESOURCE_ATTRIBUTES="deployment.environment.name=prod-eux1"')
    })

    it('wires the environment processor into the collector pipeline only when an environment is set', () => {
        logic.actions.setPlatform('collector')
        expect(logic.values.snippet).toContain('processors: [batch]')

        logic.actions.setEnvironment('production')
        expect(logic.values.snippet).toContain('processors: [resource/environment, batch]')
    })

    it('reports the copied platform and whether an environment was set', () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation(() => undefined)
        logic.actions.setPlatform('kubernetes')
        logic.actions.setEnvironment('production')
        logic.actions.snippetCopied()
        expect(capture).toHaveBeenCalledWith('tracing setup snippet copied', {
            platform: 'kubernetes',
            has_environment: true,
        })
    })
})
