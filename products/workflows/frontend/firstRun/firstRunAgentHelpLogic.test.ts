import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlowTemplateApi } from '../generated/api.schemas'
import { firstRunAgentHelpLogic } from './firstRunAgentHelpLogic'

const WELCOME = '019b6f44-f9a3-0000-c4a7-b8050d25d690'

const TEMPLATES: Partial<HogFlowTemplateApi>[] = [
    {
        id: 'onboarding',
        name: 'Onboarding',
        scope: 'global',
        starts_on: { kind: 'event', events: ['$pageview'], detail: '' },
        tags: [],
        actions: [],
    },
    {
        id: WELCOME,
        name: 'Welcome',
        scope: 'global',
        starts_on: { kind: 'event', events: ['user signed up', 'signed_up'], detail: '' },
        tags: [],
        actions: [],
    },
]

describe('firstRunAgentHelpLogic', () => {
    let logic: ReturnType<typeof firstRunAgentHelpLogic.build>
    let capture: jest.SpyInstance

    let seenEvents: string[]
    let personProperties: string[]
    let propertyRequests: number

    beforeEach(() => {
        seenEvents = []
        personProperties = []
        propertyRequests = 0
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flow_templates/': { count: TEMPLATES.length, results: TEMPLATES },
                '/api/projects/:team_id/event_definitions/': ({ request }) => {
                    const names = new URL(request.url).searchParams.get('names')?.split(',') ?? []
                    const seen = names.filter((name) => seenEvents.includes(name))
                    return [
                        200,
                        {
                            count: seen.length,
                            results: seen.map((name) => ({ id: name, name, last_seen_at: '2026-10-01T00:00:00Z' })),
                        },
                    ]
                },
                '/api/projects/:team_id/property_definitions/': ({ request }) => {
                    propertyRequests++
                    const params = new URL(request.url).searchParams
                    const names = params.get('properties')?.split(',') ?? []
                    const definitions =
                        params.get('type') === 'person' ? names.filter((name) => personProperties.includes(name)) : []
                    return [
                        200,
                        { count: definitions.length, results: definitions.map((name) => ({ id: name, name })) },
                    ]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: true })
        capture = jest.spyOn(posthog, 'capture').mockImplementation()
    })

    async function openFirstRun(project: {
        seenEvents: string[]
        personProperties: string[]
        enabled?: boolean
    }): Promise<void> {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: project.enabled ?? true })
        seenEvents = project.seenEvents
        personProperties = project.personProperties
        logic = firstRunAgentHelpLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    const agentHelpShownCalls = (): unknown[][] =>
        capture.mock.calls.filter(([event]) => event === 'workflows first run agent help shown')

    it.each([
        {
            project: 'without a signup event',
            seenEvents: ['$pageview'],
            personProperties: ['email'],
            missing: 'signup_event',
        },
        {
            project: 'with signups but no email property',
            seenEvents: ['signed_up'],
            personProperties: ['name'],
            missing: 'email',
        },
        {
            project: 'without a signup event or an email property',
            seenEvents: [],
            personProperties: [],
            missing: 'signup_event',
        },
        {
            project: 'with signups and an email property',
            seenEvents: ['signed_up', '$pageview'],
            personProperties: ['email'],
            missing: null,
        },
        {
            project: 'while first run is disabled',
            seenEvents: ['signed_up'],
            personProperties: [],
            missing: null,
            enabled: false,
        },
    ])('asks a project $project for help with missing data: $missing', async ({ missing, ...project }) => {
        await openFirstRun(project)
        if (project.enabled === false) {
            logic.actions.loadEmailProperty()
            await expectLogic(logic).toFinishAllListeners()
        }

        expect(logic.values.missingData).toEqual(missing)
        expect(agentHelpShownCalls()).toEqual(missing ? [['workflows first run agent help shown', { missing }]] : [])
        expect(propertyRequests).toEqual(project.enabled === false ? 0 : 1)
    })

    it.each([true, false])('reports a copied prompt only while first run is enabled=%s', async (enabled) => {
        await openFirstRun({ seenEvents: ['signed_up'], personProperties: [] })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: enabled })

        logic.actions.reportPromptCopied()

        if (enabled) {
            expect(capture).toHaveBeenCalledWith('workflows first run agent prompt copied', { missing: 'email' })
        } else {
            expect(capture).not.toHaveBeenCalledWith('workflows first run agent prompt copied', expect.anything())
        }
    })
})
