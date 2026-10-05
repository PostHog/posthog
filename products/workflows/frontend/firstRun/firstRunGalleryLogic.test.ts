import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { teamLogic } from 'scenes/teamLogic'

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
    let seenEvents: string[]

    beforeEach(() => {
        requestedEventNames = []
        seenEvents = []
        useMocks({
            get: {
                '/api/projects/:team_id/hog_flow_templates/': { count: TEMPLATES.length, results: TEMPLATES },
                '/api/projects/:team_id/event_definitions/': ({ request }) => {
                    const names = new URL(request.url).searchParams.get('names')?.split(',') ?? []
                    requestedEventNames.push(names)
                    const seen = names.filter((name) => seenEvents.includes(name))
                    return [200, { count: seen.length, results: seen.map((name) => ({ id: name, name })) }]
                },
            },
        })
        initKeaTests()
    })

    async function openGallery(project: { seenEvents: string[]; ingestedEvent: boolean }): Promise<void> {
        seenEvents = project.seenEvents
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
        async ({ seenEvents, ingestedEvent, recommended, welcomeMatchedEvent, picked, all }) => {
            await openGallery({ seenEvents, ingestedEvent })

            expect(logic.values.recommendedStarter?.templateId ?? null).toEqual(recommended)
            expect(
                logic.values.galleryTemplates?.find(({ template }) => template.id === WELCOME)?.matchedEvent
            ).toEqual(welcomeMatchedEvent)
            expect(shownIds()).toEqual(picked)

            logic.actions.setFilter('all')
            expect(shownIds()).toEqual(all)
        }
    )

    it('asks for every event the email templates can start on in one request', async () => {
        await openGallery({ seenEvents: [], ingestedEvent: false })

        expect(requestedEventNames).toEqual([['$pageview', 'trial_started', 'user signed up', 'signed_up', 'sign_up']])
    })

    it('reports the gallery once its fit is known, and the template a person picks', async () => {
        const capture = jest.spyOn(posthog, 'capture').mockImplementation()
        await openGallery({ seenEvents: ['signed_up', '$pageview'], ingestedEvent: true })

        expect(capture).toHaveBeenCalledWith('workflows first run gallery shown', {
            ready_count: 4,
            recommended_template_id: WELCOME,
        })

        logic.actions.pickTemplate('trial')

        expect(capture).toHaveBeenCalledWith('workflows first run template picked', {
            template_id: 'trial',
            recommended: false,
            ready: false,
        })
        expect(router.values.searchParams).toMatchObject({ templateId: 'trial' })
    })
})
