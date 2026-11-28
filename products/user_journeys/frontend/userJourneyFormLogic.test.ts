import { router } from 'kea-router'
/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { JourneyApi } from './generated/api.schemas'
import { userJourneyFormLogic } from './userJourneyFormLogic'

const CREATED: JourneyApi = {
    id: 'created-id',
    team_id: 997,
    name: 'Sign up from pricing',
    description: '',
    steps: [],
    conversion_window_minutes: 30,
    source: 'toolbar',
    created_by_id: 1,
    created_at: '2026-11-20T00:00:00Z',
    updated_at: '2026-11-20T00:00:00Z',
    latest_run: null,
}

describe('userJourneyFormLogic', () => {
    let logic: ReturnType<typeof userJourneyFormLogic.build>
    let createBody: Record<string, unknown> | null

    beforeEach(() => {
        createBody = null
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    function mockCreate(response: [number, unknown]): void {
        useMocks({
            post: {
                '/api/projects/:team_id/user_journeys/': async ({ request }) => {
                    createBody = (await request.json()) as Record<string, unknown>
                    return response
                },
            },
        })
    }

    function mountForm(url: string): void {
        router.actions.push(url)
        logic = userJourneyFormLogic({ id: 'new' })
        logic.mount()
    }

    it('creates the journey a toolbar link describes', async () => {
        mockCreate([201, CREATED])
        mountForm(
            urls.userJourneyNew({
                name: 'Sign up from pricing',
                source: 'toolbar',
                steps: [
                    { type: 'pageview', url: 'https://example.com/pricing', url_matching: 'contains' },
                    { type: 'element_click', selector: 'button.signup', text: 'Sign up' },
                ],
            })
        )

        await expectLogic(logic, () => logic.actions.submit()).toDispatchActions(['saveJourneySuccess'])

        expect(createBody).toEqual({
            name: 'Sign up from pricing',
            description: '',
            conversion_window_minutes: 30,
            source: 'toolbar',
            start_url: null,
            steps: [
                { type: 'pageview', url: 'https://example.com/pricing', url_matching: 'contains' },
                {
                    type: 'element_click',
                    selector: 'button.signup',
                    text: 'Sign up',
                    href: null,
                    url: null,
                    url_matching: 'exact',
                },
            ],
        })
        expect(router.values.location.pathname).toMatch(/\/user-journeys\/created-id$/)
    })

    it('does not send an invalid journey and shows its errors', async () => {
        mockCreate([201, CREATED])
        mountForm(urls.userJourneyNew())

        await expectLogic(logic, () => logic.actions.submit()).toNotHaveDispatchedActions(['saveJourney'])

        expect(createBody).toBeNull()
        expect(logic.values.errors).toMatchObject({
            name: 'Give the journey a name.',
            'steps.0.url': 'Enter the page URL.',
            'steps.1.selector': 'Enter a CSS selector for the element.',
        })
    })

    it('clears a stored start URL by sending an empty string, because null keeps it', async () => {
        let patchBody: Record<string, unknown> | null = null
        const stored: JourneyApi = {
            ...CREATED,
            steps: [
                { type: 'pageview', url: '/pricing', url_matching: 'contains' },
                { type: 'element_click', selector: 'button.signup' },
            ],
            start_url: 'https://example.com/pricing',
        }
        useMocks({
            get: { '/api/projects/:team_id/user_journeys/:id/': stored },
            patch: {
                '/api/projects/:team_id/user_journeys/:id/': async ({ request }) => {
                    patchBody = (await request.json()) as Record<string, unknown>
                    return [200, { ...stored, start_url: null }]
                },
            },
        })
        logic = userJourneyFormLogic({ id: CREATED.id })
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadJourneySuccess'])
        expect(logic.values.draft.start_url).toBe('https://example.com/pricing')

        logic.actions.setStartUrl('  ')
        await expectLogic(logic, () => logic.actions.submit()).toDispatchActions(['saveJourneySuccess'])

        expect(patchBody).toMatchObject({ start_url: '' })
    })

    it('shows a server validation error on the step field it names', async () => {
        mockCreate([
            400,
            {
                type: 'validation_error',
                code: 'invalid',
                detail: 'Ensure this field has no more than 1024 characters.',
                attr: 'steps__1__selector',
            },
        ])
        mountForm(
            urls.userJourneyNew({
                name: 'Sign up',
                steps: [
                    { type: 'pageview', url: '/pricing' },
                    { type: 'element_click', selector: 'button' },
                ],
            })
        )

        await expectLogic(logic, () => logic.actions.submit()).toDispatchActions(['saveJourneyFailure'])

        expect(logic.values.errors).toEqual({
            'steps.1.selector': 'Ensure this field has no more than 1024 characters.',
        })
        expect(logic.values.saving).toBe(false)
    })
})
