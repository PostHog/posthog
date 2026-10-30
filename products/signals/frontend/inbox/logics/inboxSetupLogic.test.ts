import { MOCK_DEFAULT_TEAM } from 'lib/api.mock'

import { waitFor } from '@testing-library/react'
import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import * as signalsApi from '../../generated/api'
import type {
    InboxOnboardingStateApi,
    InboxOnboardingDraftApi,
    SignalSourceConfigApi,
    SignalScoutConfigApi,
} from '../../generated/api.schemas'
import { allReports } from '../__mocks__/inboxMocks'
import { mockScoutConfigs, mockScoutSuggestionSet } from '../__mocks__/scoutConfigs'
import { signalSourcesLogic } from '../signalSourcesLogic'
import { inboxOnboardingLogic } from './inboxOnboardingLogic'
import { inboxSetupLogic } from './inboxSetupLogic'
import { scoutFleetLogic } from './scoutFleetLogic'

const draft: InboxOnboardingDraftApi = {
    step: 'github',
    sources: [{ source_product: 'error_tracking', source_type: 'issue_created', enabled: true }],
    scanner_ids: [],
    suggestions: [],

    automatic_implementation: false,
    implementation_priority: 'P1',
}

describe('Inbox setup', () => {
    let logic: ReturnType<typeof inboxSetupLogic.build>
    let savedDraft: InboxOnboardingDraftApi | null
    let sources: SignalSourceConfigApi[]
    let failCompletion: boolean
    let createdSources: number
    let inventoryRequests: number
    let canonicalScouts: SignalScoutConfigApi[]
    let enabledScouts: string[]
    let hasErrorTrackingData: boolean
    let githubOptional: boolean
    let hasEvents: boolean
    let completedAt: string | null
    let scanners: { id: string; enabled: boolean; emits_signals: boolean }[]

    function generalScoutConfig(): SignalScoutConfigApi {
        return {
            ...mockScoutConfigs[0],
            skill_name: 'signals-scout-general',
            enabled: false,
            scout_origin: 'canonical',
        }
    }

    async function connectGithub(): Promise<void> {
        const originalLocation = window.location
        Object.defineProperty(window, 'location', {
            value: { ...originalLocation, assign: jest.fn() },
            configurable: true,
        })
        try {
            await expectLogic(logic, () =>
                logic.actions.connectGithub('https://github.com/apps/example/installations/new')
            ).toFinishAllListeners()
            expect(window.location.assign).toHaveBeenCalledWith('https://github.com/apps/example/installations/new')
        } finally {
            Object.defineProperty(window, 'location', { value: originalLocation, configurable: true })
        }
    }

    function activationRequests(capture: jest.SpyInstance): unknown[][] {
        return capture.mock.calls.filter(([event]) => event === 'self-driving onboarding activation requested')
    }

    beforeEach(() => {
        window.sessionStorage.clear()
        initKeaTests()
        savedDraft = { ...draft }
        sources = []
        createdSources = 0
        inventoryRequests = 0
        canonicalScouts = []
        enabledScouts = []
        hasErrorTrackingData = false
        githubOptional = false
        hasEvents = false
        failCompletion = true
        completedAt = null
        scanners = []
        useMocks({
            get: {
                '/api/projects/:id': () => [200, { ...MOCK_DEFAULT_TEAM, ingested_event: hasEvents }],
                '/api/projects/:id/signals/reports/available_reviewers/': {},
                '/api/projects/:id/wizard/sessions/latest/': () => [204, null],
                '/api/projects/:id/signals/onboarding/': () => ({
                    draft: savedDraft,
                    completed_at: completedAt,
                    github_optional_available: githubOptional,
                }),
                '/api/projects/:id/signals/source_configs/': () => {
                    inventoryRequests++
                    return { results: sources, next: null, count: sources.length }
                },
                '/api/projects/:id/event_definitions/': () => {
                    inventoryRequests++
                    return {
                        results: hasErrorTrackingData
                            ? [{ name: '$exception', last_seen_at: '2026-10-15T00:00:00Z' }]
                            : [],
                        next: null,
                        count: hasErrorTrackingData ? 1 : 0,
                    }
                },
                '/api/projects/:id/error_tracking/issues/exists/': () => {
                    inventoryRequests++
                    return { exists: hasErrorTrackingData }
                },
                '/api/projects/:id/vision/scanners/': () => {
                    inventoryRequests++
                    return {
                        results: scanners.filter((scanner) => scanner.enabled),
                        next: null,
                        count: scanners.length,
                    }
                },
                '/api/projects/:id/signals/scout/configs/': () => canonicalScouts,
                '/api/projects/:id/signals/scout/suggestions/': mockScoutSuggestionSet({
                    status: 'low_activity',
                    items: [],
                }),
                '/api/projects/:id/integrations/': () => ({
                    results: githubOptional
                        ? []
                        : [
                              {
                                  id: 1,
                                  kind: 'github',
                                  config: {},
                                  display_name: 'example',
                                  created_at: '2026-10-14',
                                  icon_url: '',
                              },
                          ],
                    next: null,
                    count: githubOptional ? 0 : 1,
                }),
            },
            post: {
                '/api/projects/:id/signals/onboarding/expose/': () => [
                    200,
                    { draft: savedDraft, completed_at: null, github_optional_available: githubOptional },
                ],
                '/api/projects/:id/signals/scout/configs/sync/': ({ request }) => {
                    inventoryRequests++
                    expect(new URL(request.url).searchParams.get('surface')).toBe('onboarding')
                    return [200, canonicalScouts]
                },
                '/api/projects/:id/signals/scout/configs/': async ({ request }) => {
                    const config = (await request.json()) as { skill_name: string; enabled: boolean }
                    expect(config.enabled).toBe(true)
                    enabledScouts.push(config.skill_name)
                    const current = canonicalScouts.find((item) => item.skill_name === config.skill_name)!
                    Object.assign(current, config)
                    return [200, current]
                },
                '/api/projects/:id/signals/onboarding/': async ({ request }) => {
                    savedDraft = (await request.json()) as InboxOnboardingDraftApi
                    return [
                        200,
                        {
                            draft: savedDraft,
                            completed_at: completedAt,
                            github_optional_available: githubOptional,
                        },
                    ]
                },
                '/api/projects/:id/signals/config/': {},
                '/api/projects/:id/signals/source_configs/': async ({ request }) => {
                    createdSources++
                    const source = {
                        ...((await request.json()) as SignalSourceConfigApi),
                        id: '11111111-1111-4111-8111-111111111111',
                    }
                    sources.push(source)
                    return [201, source]
                },
                '/api/projects/:id/signals/onboarding/complete/': () =>
                    failCompletion
                        ? [500, { detail: 'Activation interrupted' }]
                        : [
                              200,
                              {
                                  draft: savedDraft,
                                  completed_at: '2026-10-14T12:00:00Z',
                                  github_optional_available: githubOptional,
                              },
                          ],
            },
            patch: {
                '/api/projects/:id/vision/scanners/:scanner/': async ({ request, params }) => {
                    const scanner = scanners.find((item) => item.id === params.scanner)!
                    Object.assign(scanner, await request.json())
                    return [200, scanner]
                },
                '/api/projects/:id/signals/scout/configs/:config/': async ({ request, params }) => {
                    const config = canonicalScouts.find((item) => item.id === params.config)!
                    Object.assign(config, await request.json())
                    return [200, config]
                },
                '/api/projects/:id/signals/source_configs/:source/': () => [200, sources[0]],
            },
        })
        featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SELF_DRIVING_UBP]: true })
        logic = inboxSetupLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
        jest.restoreAllMocks()
        jest.useRealTimers()
    })

    it.each([
        ['button', true, null, false],
        ['github_return', true, null, false],
        ['button', false, null, false],
        ['github_return', false, null, false],
        ['button', true, true, false],
        ['button', false, false, false],
        ['button', false, null, true],
        ['button', true, null, true],
    ] as const)(
        'activates through %s with usage-based pricing %s and saved implementation %s and GitHub-optional pilot %s',
        async (entry, usageBasedPricing, savedImplementation, pilot) => {
            githubOptional = pilot
            const capture = jest.spyOn(posthog, 'capture')
            featureFlagLogic.actions.setFeatureFlags([], {
                [FEATURE_FLAGS.SELF_DRIVING_UBP]: usageBasedPricing,
            })
            savedDraft =
                savedImplementation === null ? null : { ...draft, automatic_implementation: savedImplementation }
            failCompletion = false
            hasEvents = true
            canonicalScouts = [generalScoutConfig()]
            const refresh = jest.spyOn(signalsApi, 'signalsScoutSuggestionsRefresh')
            await expectLogic(logic, () => logic.actions.loadSetup()).toFinishAllListeners()
            expect(inventoryRequests).toBe(0)
            expect(logic.values.isQuickSetup).toBe(savedImplementation === null)
            if (savedImplementation !== null) {
                expect(logic.values.savedState?.draft?.automatic_implementation).toBe(savedImplementation)
            }
            if (entry === 'github_return') {
                await connectGithub()
                router.actions.replace(router.values.location.pathname, { onboarding_step: 'quick' })
                await waitFor(() => expect(logic.values.shouldResumeQuickSetup).toBe(true))
                logic.actions.resumeQuickSetup()
                logic.actions.resumeQuickSetup()
            } else {
                logic.actions.activateQuickSetup()
                logic.actions.activateQuickSetup()
            }
            expect(logic.values.quickActivationPending).toBe(true)
            await waitFor(() => expect(logic.values.completed).toBe(true))
            expect(inventoryRequests).toBeGreaterThan(0)
            expect(logic.values.quickActivationPending).toBe(false)
            expect(enabledScouts).toEqual(['signals-scout-general'])
            expect(logic.values.savedState?.draft?.automatic_implementation).toBe(!pilot && !usageBasedPricing)
            expect(logic.values.savedState?.draft?.suggestions.map((item) => item.skill_name)).toEqual([
                'signals-scout-general',
            ])
            expect(sources).toEqual(
                expect.arrayContaining([expect.objectContaining({ source_product: 'signals_scout', enabled: true })])
            )
            expect(router.values.searchParams.onboarding_step).toBeUndefined()
            expect(refresh).not.toHaveBeenCalled()
            expect(activationRequests(capture)).toEqual([
                [
                    'self-driving onboarding activation requested',
                    expect.objectContaining({
                        setup_mode: 'quick',
                        flow_version: 'ui-first-v1',
                        inbox_client: 'cloud',
                        activation_source: entry,
                        self_driving_ubp: usageBasedPricing,
                        automatic_implementation: !pilot && !usageBasedPricing,
                    }),
                ],
            ])
            expect(
                capture.mock.calls.filter(
                    ([event, properties]) =>
                        event === 'Signal source connected' && properties?.source_product === 'signals_scout'
                )
            ).toHaveLength(1)
        }
    )

    it.each([
        ['a missing general scout', 'scouts'],
        ['an unavailable source inventory', 'sources'],
    ] as const)('reports %s after a quick activation click and activates on retry', async (_name, failure) => {
        const capture = jest.spyOn(posthog, 'capture')
        savedDraft = null
        failCompletion = false
        hasEvents = true
        const generalScout = generalScoutConfig()
        canonicalScouts = failure === 'scouts' ? [] : [generalScout]
        let sourcesUnavailable = failure === 'sources'
        useMocks({
            get: {
                '/api/projects/:id/signals/source_configs/': () =>
                    sourcesUnavailable
                        ? [503, { detail: 'Unavailable' }]
                        : { results: sources, next: null, count: sources.length },
            },
        })
        await expectLogic(logic, () => logic.actions.loadSetup()).toFinishAllListeners()
        expect(inventoryRequests).toBe(0)
        logic.actions.activateQuickSetup()
        expect(logic.values.quickActivationPending).toBe(true)
        await waitFor(() => expect(logic.values.error).toBeTruthy())
        expect(logic.values.failedOperation).toBe(failure)
        expect(logic.values.quickActivationPending).toBe(false)
        expect(logic.values.completed).toBe(false)
        if (failure === 'scouts') {
            canonicalScouts.push(generalScout)
        } else {
            sourcesUnavailable = false
        }
        logic.actions.retry()
        await waitFor(() => expect(logic.values.completed).toBe(true))
        expect(logic.values.error).toBeNull()
        expect(activationRequests(capture)).toEqual([
            [
                'self-driving onboarding activation requested',
                expect.objectContaining({ activation_source: 'retry', setup_mode: 'quick' }),
            ],
        ])
    })

    it('does not activate from a quick-setup link unless the welcome screen started the GitHub connection', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        savedDraft = null
        failCompletion = false
        hasEvents = true
        canonicalScouts = [generalScoutConfig()]
        await expectLogic(logic, () => logic.actions.loadSetup()).toFinishAllListeners()
        router.actions.replace(router.values.location.pathname, { onboarding_step: 'github' })
        expect(logic.values.isQuickSetup).toBe(false)
        await connectGithub()
        router.actions.replace(router.values.location.pathname, { onboarding_step: 'quick' })
        await waitFor(() => expect(logic.values.shouldResumeQuickSetup).toBe(true))
        await expectLogic(logic, () => logic.actions.resumeQuickSetup()).toFinishAllListeners()
        expect(logic.values.quickActivationPending).toBe(false)
        expect(logic.values.completed).toBe(false)
        expect(inventoryRequests).toBe(0)
        expect(activationRequests(capture)).toEqual([])
        logic.actions.activateQuickSetup()
        await waitFor(() => expect(logic.values.completed).toBe(true))
        expect(activationRequests(capture)).toEqual([
            ['self-driving onboarding activation requested', expect.objectContaining({ activation_source: 'button' })],
        ])
    })

    it('reloads the onboarding state on every retry after it failed to load', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        savedDraft = null
        failCompletion = false
        hasEvents = true
        canonicalScouts = [generalScoutConfig()]
        let onboardingUnavailable = true
        useMocks({
            get: {
                '/api/projects/:id/signals/onboarding/': () =>
                    onboardingUnavailable
                        ? [503, { detail: 'Unavailable' }]
                        : [200, { draft: savedDraft, completed_at: completedAt }],
            },
        })
        await expectLogic(logic).toFinishAllListeners()
        logic.unmount()
        logic = inboxSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.error).toBeTruthy()
        expect(logic.values.savedState).toBeNull()
        logic.actions.activateQuickSetup('retry')
        expect(logic.values.quickActivationPending).toBe(true)
        await waitFor(() => expect(logic.values.error).toBeTruthy())
        expect(logic.values.quickActivationPending).toBe(false)
        await waitFor(() =>
            expect(
                logic.values.refreshingSources || logic.values.integrationsLoading || logic.values.scoutConfigsLoading
            ).toBe(false)
        )
        onboardingUnavailable = false
        logic.actions.activateQuickSetup('retry')
        expect(logic.values.quickActivationPending).toBe(true)
        await waitFor(() => expect(logic.values.completed).toBe(true))
        expect(activationRequests(capture)).toEqual([
            ['self-driving onboarding activation requested', expect.objectContaining({ activation_source: 'retry' })],
        ])
    })

    it('activates when the integration refresh fails after the inventory loaded', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        savedDraft = null
        failCompletion = false
        hasEvents = true
        canonicalScouts = [generalScoutConfig()]
        let failIntegrations: (() => void) | undefined
        const integrationsResponse = new Promise<[number, { detail: string }]>((resolve) => {
            failIntegrations = () => resolve([503, { detail: 'Unavailable' }])
        })
        await expectLogic(logic, () => logic.actions.loadSetup()).toFinishAllListeners()
        useMocks({ get: { '/api/projects/:id/integrations/': () => integrationsResponse } })
        logic.actions.activateQuickSetup()
        expect(logic.values.quickActivationPending).toBe(true)
        await waitFor(() => {
            expect(logic.values.scoutFleetSynced).toBe(true)
            expect(logic.values.refreshingSources).toBe(false)
            expect(logic.values.scoutConfigsLoading).toBe(false)
            expect(logic.values.quickSetupDraft).not.toBeNull()
        })
        expect(logic.values.integrationsLoading).toBe(true)
        expect(logic.values.completed).toBe(false)
        failIntegrations!()
        await waitFor(() => expect(logic.values.completed).toBe(true))
        expect(logic.values.hasGithubIntegration).toBe(true)
        expect(activationRequests(capture)).toEqual([
            [
                'self-driving onboarding activation requested',
                expect.objectContaining({ activation_source: 'button', github_connected: true }),
            ],
        ])
    })

    it('opens setup and preserves progress through resume and activation', async () => {
        savedDraft = null
        await expectLogic(logic, () => logic.actions.loadSetup()).toFinishAllListeners()
        expect(logic.values.inProgress).toBe(false)
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        const capture = jest.spyOn(posthog, 'capture')
        const onboarding = inboxOnboardingLogic()
        onboarding.mount()
        try {
            await expectLogic(logic, () => logic.actions.continueFromWelcome()).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.continueFromWelcome()).toFinishAllListeners()
            expect(logic.values.inProgress).toBe(true)
            expect(onboarding.values.onboardingMode).toBe('takeover')
            expect(router.values.searchParams.onboarding_step).toBe('signals')
            await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
            logic.actions.reportStepViewed()
            logic.actions.reportStepViewed()
            expect(capture.mock.calls.filter(([event]) => event === 'self-driving onboarding step viewed')).toEqual([
                [
                    'self-driving onboarding step viewed',
                    expect.objectContaining({ step: 'signals', setup_mode: 'guided' }),
                ],
            ])
            await expectLogic(logic, () => logic.actions.patchDraft({ sources: draft.sources })).toFinishAllListeners()
            expect(savedDraft).toBeNull()
            expect(capture.mock.calls.filter(([event]) => event === 'self-driving onboarding started')).toHaveLength(0)
            onboarding.unmount()
            logic.unmount()
            router.actions.replace('/inbox')
            logic = inboxSetupLogic()
            logic.mount()
            await expectLogic(logic, () => logic.actions.loadSetup()).toFinishAllListeners()
            expect(logic.values.inProgress).toBe(false)
            expect(logic.values.draft.step).toBe('signals')
            onboarding.mount()
            await expectLogic(logic, () => logic.actions.openSetup()).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.goToStep('github')).toFinishAllListeners()
            expect(savedDraft).toMatchObject({ step: 'github' })
            logic.actions.reportStepViewed()
            await expectLogic(logic, () => logic.actions.goToStep('signals')).toFinishAllListeners()
            logic.actions.reportStepViewed()
            expect(capture.mock.calls.filter(([event]) => event === 'self-driving onboarding step completed')).toEqual([
                ['self-driving onboarding step completed', expect.objectContaining({ step: 'signals' })],
            ])
            await expectLogic(logic, () => logic.actions.goToStep('github')).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.patchDraft({ sources: draft.sources })).toFinishAllListeners()
            expect(capture.mock.calls.filter(([event]) => event === 'self-driving onboarding started')).toHaveLength(1)
            expect(capture).toHaveBeenCalledWith(
                'self-driving onboarding started',
                expect.objectContaining({ setup_mode: 'guided' })
            )
            expect(
                capture.mock.calls.filter(([event]) => event === 'self-driving onboarding welcome continued')
            ).toHaveLength(1)
            expect(capture.mock.calls.filter(([event]) => event === 'Inbox welcome manual setup clicked')).toHaveLength(
                1
            )
        } finally {
            onboarding.unmount()
            capture.mockRestore()
        }
        logic.unmount()
        router.actions.replace('/inbox')
        logic = inboxSetupLogic()
        logic.mount()
        await expectLogic(logic, () => logic.actions.loadSetup()).toFinishAllListeners()
        expect(logic.values.inProgress).toBe(true)
        expect(logic.values.draft.step).toBe('github')
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        const resumedCapture = jest.spyOn(posthog, 'capture')
        logic.actions.reportStepViewed()
        expect(resumedCapture).toHaveBeenCalledWith(
            'self-driving onboarding step viewed',
            expect.objectContaining({
                step: 'github',
                implementation_toggle_shown: true,
            })
        )
        failCompletion = false
        await expectLogic(logic, () => logic.actions.activate()).toFinishAllListeners()
        expect(logic.values.completed).toBe(true)
        expect(logic.values.inProgress).toBe(false)
        expect(resumedCapture).toHaveBeenCalledWith(
            'self-driving onboarding step completed',
            expect.objectContaining({ step: 'github' })
        )
    })

    it('shows the paused reminder when a project with reports stops watching anything', async () => {
        savedDraft = null
        sources = [
            {
                ...draft.sources[0],
                id: 'source-one',
                created_at: '2026-10-14T12:00:00Z',
                updated_at: '2026-10-14T12:00:00Z',
                status: null,
            },
        ]
        useMocks({
            get: {
                '/api/projects/:id/signals/reports/': {
                    results: allReports.slice(0, 1),
                    count: 1,
                    next: null,
                    previous: null,
                },
            },
        })
        await expectLogic(logic, () => logic.actions.loadSetup()).toFinishAllListeners()
        const onboarding = inboxOnboardingLogic()
        onboarding.mount()
        try {
            await expectLogic(onboarding, () => {
                onboarding.actions.refreshSetupState()
                signalSourcesLogic.actions.loadVisionScanners()
            }).toFinishAllListeners()
            await waitFor(() => expect(onboarding.values.isSetupLoaded).toBe(true))
            expect(logic.values.completed).toBe(false)
            expect(onboarding.values.onboardingMode).toBe('none')

            sources[0].enabled = false
            await expectLogic(signalSourcesLogic, () =>
                signalSourcesLogic.actions.loadSourceConfigs()
            ).toFinishAllListeners()
            await waitFor(() => expect(onboarding.values.onboardingMode).toBe('banner'))
            expect(logic.values.completed).toBe(false)
        } finally {
            onboarding.unmount()
        }
    })

    it.each([
        { usageBasedPricing: true, detail: 'Activation interrupted', status: 400 },
        { usageBasedPricing: false, detail: 'Activation interrupted', status: 503 },
        { usageBasedPricing: true, detail: null, status: 503 },
        { usageBasedPricing: true, detail: ' ', status: 500 },
    ])(
        'retries partial activation with pricing $usageBasedPricing and detail $detail',
        async ({ usageBasedPricing, detail, status }) => {
            featureFlagLogic.actions.setFeatureFlags([], { [FEATURE_FLAGS.SELF_DRIVING_UBP]: usageBasedPricing })
            const capture = jest.spyOn(posthog, 'capture')
            const captureException = jest.spyOn(posthog, 'captureException').mockImplementation(() => undefined)
            useMocks({
                post: {
                    '/api/projects/:id/signals/onboarding/complete/': () =>
                        failCompletion
                            ? [status, { detail, code: 'activation_interrupted' }]
                            : [200, { draft: savedDraft, completed_at: '2026-10-14T12:00:00Z' }],
                },
            })
            await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
            expect(logic.values.activationDisabledReason).toBeUndefined()
            expect(capture.mock.calls.filter(([event]) => event === 'self-driving onboarding started')).toHaveLength(0)
            await expectLogic(logic, () => logic.actions.activate()).toFinishAllListeners()
            expect(logic.values.completed).toBe(false)
            expect(logic.values.inProgress).toBe(true)
            expect(logic.values.draft).toEqual({ ...draft, automatic_implementation: !usageBasedPricing })
            const message = detail?.trim() || 'Could not finish setup. Your choices are saved. Retry activation.'
            expect(logic.values.error).toBe(message)
            expect(logic.values.failedOperation).toBe('activation')
            expect(logic.values.saving).toBe(false)
            expect(captureException).toHaveBeenCalledWith(
                expect.objectContaining({ status, code: 'activation_interrupted' }),
                { operation: 'inbox_activation', http_status: status, error_code: 'activation_interrupted' }
            )
            expect(createdSources).toBe(1)

            failCompletion = false
            await expectLogic(logic, () => logic.actions.retry()).toFinishAllListeners()
            expect(savedDraft?.automatic_implementation).toBe(!usageBasedPricing)
            expect(logic.values.completed).toBe(true)
            expect(logic.values.inProgress).toBe(false)
            expect(createdSources).toBe(1)
            expect(capture.mock.calls.filter(([event]) => event === 'self-driving onboarding started')).toHaveLength(1)
            expect(capture.mock.calls.filter(([event]) => event === 'Signal source connected')).toEqual([
                [
                    'Signal source connected',
                    expect.objectContaining({
                        source_product: 'error_tracking',
                        is_first_connection: true,
                        setup_mode: 'guided',
                    }),
                    undefined,
                ],
            ])
            expect(capture.mock.calls.filter(([event]) => event === 'self-driving onboarding failed')).toEqual([
                [
                    'self-driving onboarding failed',
                    expect.objectContaining({
                        failed_operation: 'activation',
                        step: 'github',
                        flow_version: 'ui-first-v1',
                        http_status: status,
                        error_code: 'activation_interrupted',
                        error_message: message,
                    }),
                ],
            ])
            expect(capture).toHaveBeenCalledWith(
                'self-driving onboarding activation requested',
                expect.objectContaining({ activation_source: 'retry' })
            )
            capture.mockRestore()
        }
    )

    it('preserves a committed activation when its completion response was lost', async () => {
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        logic.actions.setEditedDraft({ ...logic.values.draft, automatic_implementation: true })
        const writeConfig = jest.spyOn(signalsApi, 'signalsConfigCreate')
        const complete = jest.spyOn(signalsApi, 'signalsOnboardingCompleteCreate').mockImplementation(async () => {
            completedAt = '2026-10-14T12:00:00Z'
            throw new Error('Response lost')
        })
        await expectLogic(logic, () => logic.actions.activate()).toFinishAllListeners()
        expect(logic.values.completed).toBe(false)
        expect(writeConfig).toHaveBeenCalledTimes(1)
        await expectLogic(logic, () => logic.actions.retry()).toFinishAllListeners()
        expect(logic.values.completed).toBe(true)
        expect(writeConfig).toHaveBeenCalledTimes(1)
        expect(complete).toHaveBeenCalledTimes(1)
        expect(savedDraft?.automatic_implementation).toBe(true)
    })

    it('disables a scanner deselected after partially successful activation', async () => {
        scanners = [{ id: 'scanner-one', enabled: true, emits_signals: false }]
        savedDraft = { ...draft, scanner_ids: ['scanner-one'] }
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.activate()).toFinishAllListeners()
        expect(scanners[0].emits_signals).toBe(true)
        expect(logic.values.completed).toBe(false)
        logic.actions.setEditedDraft({ ...logic.values.draft, scanner_ids: [] })
        failCompletion = false
        await expectLogic(logic, () => logic.actions.activate()).toFinishAllListeners()
        expect(scanners[0].emits_signals).toBe(false)
        expect(logic.values.completed).toBe(true)
    })

    it('preserves selected scanners when inventory refresh fails', async () => {
        scanners = [{ id: 'scanner-one', enabled: true, emits_signals: false }]
        savedDraft = { ...draft, scanner_ids: ['scanner-one'] }
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        useMocks({ get: { '/api/projects/:id/vision/scanners/': () => [500, { detail: 'Unavailable' }] } })
        await expectLogic(signalSourcesLogic, () =>
            signalSourcesLogic.actions.loadVisionScanners()
        ).toFinishAllListeners()
        expect(logic.values.draft.scanner_ids).toEqual(['scanner-one'])
    })

    it.each([false, true])('handles unavailable scanner access with selected scanners: %s', async (selected) => {
        savedDraft = { ...draft, scanner_ids: selected ? ['scanner-one'] : [] }
        failCompletion = false
        useMocks({ get: { '/api/projects/:id/vision/scanners/': () => [403, { detail: 'Scanner access denied' }] } })
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.activate()).toFinishAllListeners()
        expect(logic.values.completed).toBe(!selected)
        expect(logic.values.error).toBe(selected ? 'Scanner access denied' : null)
    })

    it('retries source inventory after a failed background refresh', async () => {
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        let unavailable = true
        const recoveredSource = {
            id: 'recovered-source',
            source_product: 'error_tracking',
            source_type: 'issue_created',
            enabled: true,
        }
        useMocks({
            get: {
                '/api/projects/:id/signals/source_configs/': () =>
                    unavailable
                        ? [503, { detail: 'Unavailable' }]
                        : { results: [recoveredSource], next: null, count: 1 },
            },
        })
        await expectLogic(logic, () => logic.actions.refreshSources()).toFinishAllListeners()
        expect(logic.values.ready).toBe(true)
        expect(logic.values.error).toBeTruthy()
        unavailable = false
        await expectLogic(logic, () => logic.actions.retry()).toFinishAllListeners()
        expect(logic.values.sourceConfigs).toEqual([recoveredSource])
        expect(logic.values.error).toBeNull()
    })

    it('recovers scout choices after materialization fails', async () => {
        useMocks({ post: { '/api/projects/:id/signals/scout/configs/sync/': () => [503, { detail: 'Unavailable' }] } })
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        expect(logic.values.error).toBe('Could not prepare your scouts. Try again.')
        const generalScout = { ...mockScoutConfigs[0], skill_name: 'signals-scout-general', enabled: false }
        useMocks({ post: { '/api/projects/:id/signals/scout/configs/sync/': () => [200, [generalScout]] } })
        await expectLogic(logic, () => logic.actions.retry()).toFinishAllListeners()
        expect(logic.values.scoutChoices.some((scout) => scout.skill_name === generalScout.skill_name)).toBe(true)
        expect(logic.values.error).toBeNull()
    })

    it.each([false, true])(
        'reconciles deselected scouts after reload without changing pre-existing enablement (%s)',
        async (enabledBeforeSetup) => {
            const suggestion = {
                ...mockScoutSuggestionSet().items[0],
                kind: 'canonical' as const,
                skill_name: 'signals-scout-general',
            }
            canonicalScouts = [
                { ...mockScoutConfigs[0], skill_name: suggestion.skill_name, enabled: enabledBeforeSetup },
            ]
            savedDraft = { ...draft, suggestions: [suggestion] }
            await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
            await expectLogic(logic, () => logic.actions.activate()).toFinishAllListeners()
            expect(canonicalScouts[0].enabled).toBe(true)
            expect(logic.values.completed).toBe(false)
            logic.unmount()
            logic = inboxSetupLogic()
            logic.mount()
            await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
            logic.actions.setEditedDraft({ ...logic.values.draft, suggestions: [] })
            failCompletion = false
            await expectLogic(logic, () => logic.actions.activate()).toFinishAllListeners()
            expect(canonicalScouts[0].enabled).toBe(enabledBeforeSetup)
            expect(logic.values.completed).toBe(true)
        }
    )

    it.each(['product-analytics', 'general'])('keeps %s scout edits during reloads until activation', async (name) => {
        hasEvents = name === 'product-analytics'
        const skillName = `signals-scout-${name}`
        canonicalScouts = [{ ...mockScoutConfigs[0], skill_name: skillName, enabled: false }]
        savedDraft = { ...draft, step: 'scouts' }
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        const suggestion = logic.values.scoutChoices.find((item) => item.skill_name === skillName)
        expect(suggestion).not.toBeUndefined()
        await expectLogic(logic, () => logic.actions.toggleSuggestion(suggestion!)).toFinishAllListeners()
        expect(savedDraft?.suggestions).toEqual([suggestion])
        expect(enabledScouts).toEqual([])
        const selectedState: InboxOnboardingStateApi = { draft: savedDraft, completed_at: null }
        let finishReload!: (state: InboxOnboardingStateApi) => void
        jest.spyOn(signalsApi, 'signalsOnboardingList').mockImplementationOnce(
            () =>
                new Promise((resolve) => {
                    finishReload = resolve
                })
        )
        logic.actions.loadSetup()
        logic.actions.toggleSuggestion(suggestion!)
        expect(logic.values.draft.suggestions).toEqual([])
        finishReload(selectedState)
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.draft.suggestions).toEqual([])
        expect(savedDraft?.suggestions).toEqual([])
        logic.unmount()
        logic = inboxSetupLogic()
        logic.mount()
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        expect(logic.values.draft.suggestions).toEqual([])
        await expectLogic(logic, () => logic.actions.toggleSuggestion(suggestion!)).toFinishAllListeners()
        await expectLogic(logic, () => logic.actions.goToStep('github')).toFinishAllListeners()
        failCompletion = false
        await expectLogic(logic, () => logic.actions.activate()).toFinishAllListeners()
        expect(enabledScouts).toEqual([skillName])
        expect(logic.values.completed).toBe(true)
    })

    it.each(['signals', 'scouts', 'github'] as const)(
        'only waits for scouts on the second step when viewing %s',
        async (step) => {
            savedDraft = { ...draft, step }
            await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
            let finishLoading!: () => void
            const pending = new Promise<void>((resolve) => {
                finishLoading = resolve
            })
            useMocks({
                get: {
                    '/api/projects/:id/signals/scout/configs/': async () => {
                        await pending
                        return [200, []]
                    },
                },
            })
            scoutFleetLogic.actions.loadScoutConfigs()
            expect(logic.values.scoutsLoading).toBe(true)
            expect(logic.values.ready).toBe(step !== 'scouts')
            finishLoading()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.ready).toBe(true)
        }
    )

    it('keeps GitHub as the final step for an existing connection', async () => {
        savedDraft = { ...draft, step: 'scouts' }
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        expect(logic.values.isFinalStep).toBe(false)
        await expectLogic(logic, () => logic.actions.goToStep('github')).toFinishAllListeners()
        expect(logic.values.draft.step).toBe('github')
        expect(logic.values.isFinalStep).toBe(true)
        expect(logic.values.activationDisabledReason).toBeUndefined()
    })

    it.each(['refresh', 'return'] as const)(
        'updates saved source choices on %s without undoing explicit deselection',
        async (mode) => {
            savedDraft = { ...draft, step: 'signals', sources: [] }
            await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
            expect(logic.values.draft.sources).toEqual([])
            await expectLogic(logic, () => logic.actions.goToStep('scouts')).toFinishAllListeners()

            hasErrorTrackingData = true
            if (mode === 'return') {
                logic.unmount()
                logic = inboxSetupLogic()
                logic.mount()
                await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
            } else {
                await expectLogic(logic, () => logic.actions.refreshSources()).toFinishAllListeners()
            }
            const source = logic.values.sources.find((item) => item.definition.source === 'error_tracking')!
            expect(source.available).toBe(true)
            expect(logic.values.draft.sources).toEqual(source.sources)
            expect(logic.values.draft.step).toBe('scouts')
            await expectLogic(logic, () => logic.actions.goToStep('github')).toFinishAllListeners()
            expect(savedDraft?.sources).toEqual(source.sources)

            await expectLogic(logic, () => logic.actions.toggleSource(source, false)).toFinishAllListeners()
            logic.unmount()
            logic = inboxSetupLogic()
            logic.mount()
            await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
            expect(logic.values.draft.sources).toEqual(source.sources.map((item) => ({ ...item, enabled: false })))
        }
    )

    it('batches rapid edits without locking the form', async () => {
        const capture = jest.spyOn(posthog, 'capture')
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        const save = jest.spyOn(signalsApi, 'signalsOnboardingCreate').mockImplementation(async (_, draft) => ({
            draft,
            completed_at: null,
        }))
        jest.useFakeTimers()
        logic.actions.patchDraft({ automatic_implementation: true })
        await jest.advanceTimersByTimeAsync(500)
        logic.actions.patchDraft({ implementation_priority: 'P2' })
        expect(logic.values.draft).toMatchObject({ automatic_implementation: true, implementation_priority: 'P2' })
        expect(logic.values.saving).toBe(false)
        await jest.advanceTimersByTimeAsync(749)
        expect(save).not.toHaveBeenCalled()
        await jest.advanceTimersByTimeAsync(1)
        expect(save).toHaveBeenCalledTimes(1)
        expect(save.mock.calls[0][1]).toMatchObject({ automatic_implementation: true, implementation_priority: 'P2' })
        expect(
            capture.mock.calls.filter(([event]) => event === 'self-driving onboarding implementation changed')
        ).toEqual([
            [
                'self-driving onboarding implementation changed',
                expect.objectContaining({
                    previous_value: false,
                    new_value: true,
                    setup_mode: 'guided',
                    self_driving_ubp: true,
                }),
            ],
        ])
    })

    it('serializes saves and keeps newer edits while navigation waits for them', async () => {
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        let finishFirst!: (state: InboxOnboardingStateApi) => void
        let finishSecond!: (state: InboxOnboardingStateApi) => void
        const save = jest
            .spyOn(signalsApi, 'signalsOnboardingCreate')
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        finishFirst = resolve
                    })
            )
            .mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        finishSecond = resolve
                    })
            )
        logic.actions.patchDraft({ automatic_implementation: true })
        await waitFor(() => expect(save).toHaveBeenCalledTimes(1))
        expect(logic.values.saving).toBe(false)
        logic.actions.patchDraft({ automatic_implementation: false, implementation_priority: 'P2' })
        logic.actions.goToStep('scouts')
        expect(save).toHaveBeenCalledTimes(1)
        expect(logic.values.saving).toBe(true)
        finishFirst({ draft: save.mock.calls[0][1], completed_at: null })
        await waitFor(() => expect(save).toHaveBeenCalledTimes(2))
        expect(logic.values.draft).toMatchObject({ automatic_implementation: false, implementation_priority: 'P2' })
        expect(router.values.searchParams.onboarding_step).not.toBe('scouts')
        finishSecond({ draft: save.mock.calls[1][1], completed_at: null })
        await expectLogic(logic).toFinishAllListeners()
        expect(save).toHaveBeenCalledTimes(2)
        expect(logic.values.saving).toBe(false)
        expect(router.values.searchParams.onboarding_step).toBe('scouts')
        expect(logic.values.savedState?.draft).toMatchObject({
            automatic_implementation: false,
            implementation_priority: 'P2',
        })
    })

    it('keeps failed edits and retries before leaving for GitHub', async () => {
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        const originalLocation = window.location
        const assign = jest.fn()
        Object.defineProperty(window, 'location', { configurable: true, value: { ...originalLocation, assign } })
        const save = jest.spyOn(signalsApi, 'signalsOnboardingCreate').mockRejectedValueOnce(new Error('Offline'))
        try {
            await expectLogic(logic, () =>
                logic.actions.patchDraft({ automatic_implementation: true })
            ).toFinishAllListeners()
            expect(logic.values.error).toContain('Could not save')
            expect(logic.values.draft.automatic_implementation).toBe(true)
            expect(logic.values.saving).toBe(false)
            let finish!: (state: InboxOnboardingStateApi) => void
            save.mockImplementationOnce(
                () =>
                    new Promise((resolve) => {
                        finish = resolve
                    })
            )
            logic.actions.connectGithub('/authorize-github')
            expect(assign).not.toHaveBeenCalled()
            expect(logic.values.saving).toBe(true)
            finish({ draft: save.mock.calls[1][1], completed_at: null })
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.error).toBeNull()
            expect(assign).toHaveBeenCalledWith('/authorize-github')
            expect(logic.values.savedState?.draft?.automatic_implementation).toBe(true)
        } finally {
            Object.defineProperty(window, 'location', { configurable: true, value: originalLocation })
        }
    })

    it('persists final-step choices so they survive leaving for GitHub', async () => {
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        await expectLogic(logic, () =>
            logic.actions.patchDraft({ automatic_implementation: true })
        ).toFinishAllListeners()
        logic.unmount()
        logic = inboxSetupLogic()
        logic.mount()
        await expectLogic(logic, () => logic.actions.startSetup()).toFinishAllListeners()
        expect(logic.values.isFinalStep).toBe(true)
        expect(logic.values.draft).toMatchObject({
            step: 'github',
            automatic_implementation: true,
        })
    })
})
