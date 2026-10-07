import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { HogFlowTemplateApi } from '../generated/api.schemas'
import { firstRunGalleryLogic } from './firstRunGalleryLogic'

const WELCOME = '019b6f44-f9a3-0000-c4a7-b8050d25d690'

function emailTemplate(id: string, startsOn: HogFlowTemplateApi['starts_on']): Partial<HogFlowTemplateApi> {
    return {
        id,
        name: id,
        scope: 'global',
        starts_on: startsOn,
        tags: [],
        actions: [],
    }
}

const TEMPLATES: Partial<HogFlowTemplateApi>[] = [
    emailTemplate('onboarding', { kind: 'event', events: ['$pageview'], detail: 'on /onboarding' }),
    emailTemplate('trial', { kind: 'event', events: ['trial_started'], detail: '' }),
    emailTemplate(WELCOME, { kind: 'event', events: ['user signed up', 'signed_up', 'sign_up'], detail: '' }),
    emailTemplate('re-engagement', { kind: 'no_event', events: ['$pageview'], detail: 'for 14 days' }),
    emailTemplate('unused-features', { kind: 'schedule', events: [], detail: 'every 10 days' }),
    { ...emailTemplate('slack-alert', null), name: 'A global template without email' },
    { ...emailTemplate('team-email', null), scope: 'team' },
]

describe('firstRunGalleryLogic', () => {
    let logic: ReturnType<typeof firstRunGalleryLogic.build>
    let requestedEventNames: string[][]
    let templateRequests: number
    let seenEvents: string[]
    let plannedEvents: string[]

    beforeEach(() => {
        requestedEventNames = []
        templateRequests = 0
        seenEvents = []
        plannedEvents = []
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flow_templates/': () => {
                    templateRequests++
                    return [200, { count: TEMPLATES.length, results: TEMPLATES }]
                },
                '/api/projects/:team_id/event_definitions/': ({ request }) => {
                    const names = new URL(request.url).searchParams.get('names')?.split(',') ?? []
                    requestedEventNames.push(names)
                    const definitions = names
                        .filter((name) => seenEvents.includes(name) || plannedEvents.includes(name))
                        .map((name) => ({
                            id: name,
                            name,
                            last_seen_at: seenEvents.includes(name) ? '2026-10-01T00:00:00Z' : null,
                        }))
                        .reverse()
                    return [200, { count: definitions.length, results: definitions }]
                },
            },
        })
        initKeaTests()
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: true })
    })

    async function openGallery(project: {
        seenEvents: string[]
        plannedEvents?: string[]
        ingestedEvent: boolean
        enabled?: boolean
    }): Promise<void> {
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: project.enabled ?? true })
        seenEvents = project.seenEvents
        plannedEvents = project.plannedEvents ?? []
        teamLogic.actions.loadCurrentTeamSuccess({ ...MOCK_DEFAULT_TEAM, ingested_event: project.ingestedEvent })
        logic = firstRunGalleryLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
    }

    afterEach(() => {
        logic?.unmount()
        jest.restoreAllMocks()
    })

    const shownIds = (): string[] => logic.values.shownTemplates.map(({ template }) => template.id)

    it.each([
        {
            project: 'that sends signups and pageviews',
            seenEvents: ['signed_up', '$pageview'],
            ingestedEvent: true,
            recommended: WELCOME,
            welcomeMatchedEvent: 'signed_up',
            picked: [WELCOME, 'onboarding', 're-engagement', 'unused-features'],
            all: [WELCOME, 'onboarding', 're-engagement', 'unused-features', 'trial'],
        },
        {
            project: 'that sends only pageviews',
            seenEvents: ['$pageview'],
            ingestedEvent: true,
            recommended: 'onboarding',
            welcomeMatchedEvent: null,
            picked: ['onboarding', 're-engagement', 'unused-features'],
            all: ['onboarding', 're-engagement', 'unused-features', 'trial', WELCOME],
        },
        {
            project: 'that sends several signup events',
            seenEvents: ['sign_up', 'user signed up'],
            ingestedEvent: true,
            recommended: WELCOME,
            welcomeMatchedEvent: 'user signed up',
            picked: [WELCOME, 'unused-features'],
            all: [WELCOME, 'unused-features', 'onboarding', 'trial', 're-engagement'],
        },
        {
            project: 'that only planned a signup event and sends pageviews',
            seenEvents: ['$pageview'],
            plannedEvents: ['signed_up'],
            ingestedEvent: true,
            recommended: 'onboarding',
            welcomeMatchedEvent: null,
            picked: ['onboarding', 're-engagement', 'unused-features'],
            all: ['onboarding', 're-engagement', 'unused-features', 'trial', WELCOME],
        },
        {
            project: 'that sends only events no template starts on',
            seenEvents: [],
            ingestedEvent: true,
            recommended: 'unused-features',
            welcomeMatchedEvent: null,
            picked: ['unused-features'],
            all: ['unused-features', 'onboarding', 'trial', WELCOME, 're-engagement'],
        },
        {
            project: 'that sends no events',
            seenEvents: [],
            ingestedEvent: false,
            recommended: null,
            welcomeMatchedEvent: null,
            picked: ['onboarding', 'trial', WELCOME, 're-engagement', 'unused-features'],
            all: ['onboarding', 'trial', WELCOME, 're-engagement', 'unused-features'],
        },
    ])(
        'tailors the gallery to a project $project',
        async ({ recommended, welcomeMatchedEvent, picked, all, ...project }) => {
            await openGallery(project)

            expect(logic.values.recommendedStarter?.templateId ?? null).toEqual(recommended)
            expect(
                logic.values.galleryTemplates?.find(({ template }) => template.id === WELCOME)?.matchedEvent
            ).toEqual(welcomeMatchedEvent)
            expect(shownIds()).toEqual(picked)

            logic.actions.setFilter('all')
            expect(shownIds()).toEqual(all)
        }
    )

    it.each([true, false])('loads template fit only while first run is enabled=%s', async (enabled) => {
        await openGallery({ seenEvents: [], ingestedEvent: false, enabled })
        if (!enabled) {
            logic.actions.loadEmailTemplates()
            await expectLogic(logic).toFinishAllListeners()
        }

        expect(templateRequests).toEqual(enabled ? 1 : 0)
        expect(requestedEventNames).toEqual(
            enabled ? [['$pageview', 'trial_started', 'user signed up', 'signed_up', 'sign_up']] : []
        )
    })

    it('reports the gallery once its fit is known', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        await openGallery({ seenEvents: ['signed_up', '$pageview'], ingestedEvent: true })

        expect(capture).toHaveBeenCalledWith('workflows first run gallery shown', {
            ready_count: 4,
            recommended_template_id: WELCOME,
        })
    })

    it.each([
        { pick: 'the recommended starter', templateId: WELCOME, recommended: true, ready: true, enabled: true },
        { pick: 'another ready template', templateId: 'onboarding', recommended: false, ready: true, enabled: true },
        { pick: 'a template that is not ready', templateId: 'trial', recommended: false, ready: false, enabled: true },
        {
            pick: 'a loaded template after disabling first run',
            templateId: WELCOME,
            recommended: true,
            ready: true,
            enabled: false,
        },
    ])('honors the flag when picking $pick', async ({ templateId, recommended, ready, enabled }) => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        await openGallery({ seenEvents: ['signed_up', '$pageview'], ingestedEvent: true })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.WORKFLOWS_FIRST_RUN]: enabled })
        const originalSearchParams = router.values.searchParams

        logic.actions.pickTemplate(templateId)

        if (enabled) {
            expect(capture).toHaveBeenCalledWith('workflows first run template picked', {
                template_id: templateId,
                recommended,
                ready,
            })
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(urls.workflows())
            expect(router.values.searchParams).toEqual({ template: templateId })
        } else {
            expect(capture).not.toHaveBeenCalledWith('workflows first run template picked', expect.anything())
            expect(router.values.searchParams).toEqual(originalSearchParams)
        }
    })

    it.each([
        { failing: 'the templates request', endpoint: '/api/projects/:team_id/hog_flow_templates/' },
        { failing: 'the event definitions request', endpoint: '/api/projects/:team_id/event_definitions/' },
    ])('offers a retry when $failing fails, and recovers on it', async ({ endpoint }) => {
        silenceKeaLoadersErrors()
        let failing = true
        const healthyResponse = endpoint.includes('templates')
            ? { count: TEMPLATES.length, results: TEMPLATES }
            : { count: 0, results: [] }
        useMocks({ get: { [endpoint]: () => (failing ? [500, { detail: 'Server error' }] : [200, healthyResponse]) } })

        try {
            await openGallery({ seenEvents: [], ingestedEvent: true })
            expect(logic.values).toMatchObject({ galleryLoadFailed: true, galleryTemplates: null })

            failing = false
            logic.actions.loadEmailTemplates()
            await expectLogic(logic).toFinishAllListeners()

            expect(logic.values.galleryLoadFailed).toBe(false)
            expect(logic.values.galleryTemplates).toHaveLength(5)
        } finally {
            resumeKeaLoadersErrors()
        }
    })
})
