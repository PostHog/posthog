import { MOCK_TEAM_ID } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { parseCsvParam, parseNumericParam, parseSortParam } from '../utils/urlParams'
import { consumeGoalDraftIntent, markGoalDraftIntent } from './goalDraftIntent'
import {
    buildObservationListParams,
    ObservationStatusValue,
    ObservationTriggeredByValue,
    ObservationVerdictValue,
    replayScannerLogic,
    shouldGuardScannerNavigation,
} from './replayScannerLogic'
import { readScannerDraft, writeScannerDraft } from './scannerDraft'
import { scannerEditorSceneLogic } from './scannerEditorSceneLogic'
import { observationsDrilldownSearchParams } from './scannerOverviewLogic'
import { defaultScannerTemplates } from './scannerTemplates'
import { ClassifierScanner, ReplayScanner, ScorerScanner } from './types'

jest.mock('lib/forms/scrollToFormError', () => ({
    scrollToFormError: jest.fn(),
}))

describe('replayScannerLogic', () => {
    let logic: ReturnType<typeof replayScannerLogic.build>
    let observeSpy: jest.Mock
    let retrySpy: jest.Mock
    let suggestSpy: jest.Mock
    let createSpy: jest.Mock
    let draftSpy: jest.Mock

    beforeEach(() => {
        observeSpy = jest.fn(() => [202, { workflow_id: 'wf-test' }])
        retrySpy = jest.fn(() => [202, { workflow_id: 'wf-retry' }])
        suggestSpy = jest.fn(() => [200, { suggestions: [] }])
        createSpy = jest.fn(() => [201, { id: 'created-scanner' }])
        draftSpy = jest.fn(() => [200, {}])
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/': () => [404, {}],
                '/api/projects/:team/vision/scanners/:id/observations/': { results: [] },
                '/api/projects/:team/vision/scanners/:id/observations/stats/': {
                    status_counts: { total: 0, succeeded: 0, failed: 0, ineligible: 0, in_flight: 0 },
                    coverage: { recent_sessions: 0, total_sessions: 0, recent_days: 14 },
                    available_tags: [],
                },
            },
            post: {
                '/api/projects/:team/vision/scanners/': createSpy,
                '/api/projects/:team/vision/scanners/:id/observe/': observeSpy,
                '/api/projects/:team/vision/observations/:id/retry/': retrySpy,
                '/api/projects/:team/vision/scanners/suggest_tags/': suggestSpy,
                '/api/projects/:team/vision/scanners/draft/': draftSpy,
            },
        })
        // The draft layer persists form edits to localStorage and the nudge hand-off marker to
        // sessionStorage; without a reset, one test's state bleeds into the next.
        localStorage.clear()
        sessionStorage.clear()
        initKeaTests()
        logic = replayScannerLogic({ id: 'new' })
        logic.mount()
        // The submit handler reads the wizard step from scannerEditorSceneLogic, so mount it too.
        scannerEditorSceneLogic.mount()
    })

    afterEach(() => {
        logic?.unmount()
        scannerEditorSceneLogic.unmount()
    })

    describe('form defaults', () => {
        it('new scanner starts as monitor with empty prompt and default sampling', () => {
            expect(logic.values.scanner).toMatchObject({
                id: 'new',
                name: 'MockHog App + Marketing monitor',
                enabled: true,
                scanner_type: 'monitor',
                scanner_config: { prompt: '' },
                sampling_rate: 0.2,
                sampling_mode: 'balanced',
            })
        })

        it('new scanner pre-fills from ?template= search param', async () => {
            const template = defaultScannerTemplates.find((t) => t.key === 'dead_end')!
            router.actions.push('/replay-vision/new', { template: template.key })
            await expectLogic(logic, () => logic.actions.loadScanner()).toMatchValues({
                scanner: expect.objectContaining({
                    name: template.scanner_name,
                    description: template.scanner_description,
                    scanner_type: template.scanner_type,
                    scanner_config: template.scanner_config,
                }),
            })
        })
    })

    describe('draftScannerFromGoal', () => {
        // The box renders on the editor's template step and on the zero-scanner empty state.
        it.each([
            ['the template step', urls.replayVisionScannerTemplate('new')],
            ['the empty scanner list', urls.replayVision()],
        ])('seeds the form from the AI draft and routes to the details step from %s', async (_origin, path) => {
            const draft = {
                name: 'User intent',
                description: 'Tags each session by intent.',
                scanner_type: 'classifier',
                scanner_config: { prompt: 'Classify the session by intent.', tags: ['browsing'], multi_label: false },
                rationale: 'A classifier fits because you want the mix of visit intents.',
                query: {
                    kind: 'RecordingsQuery',
                    events: [{ id: 'signed_up', name: 'signed_up', type: 'events', order: 0 }],
                },
            }
            draftSpy.mockReturnValue([200, draft])
            router.actions.push(path)
            logic.actions.setGoalDraftInput('understand what users come here to do')

            await expectLogic(logic, () =>
                logic.actions.draftScannerFromGoal('understand what users come here to do')
            ).toFinishAllListeners()

            expect(draftSpy).toHaveBeenCalled()
            expect(logic.values.goalDraftInput).toEqual('')
            expect(logic.values.scanner).toMatchObject({
                name: draft.name,
                description: draft.description,
                scanner_type: draft.scanner_type,
                scanner_config: draft.scanner_config,
                query: draft.query,
            })
            // The test router prefixes paths with /project/:id, so match on the suffix.
            expect(router.values.location.pathname).toContain(urls.replayVisionScannerDetails('new'))

            // The rationale stays available for the configure step, until a template pick replaces the draft.
            expect(logic.values.goalDraft?.rationale).toEqual(draft.rationale)
            logic.actions.startFromTemplate(null)
            expect(logic.values.goalDraft).toBeNull()
        })

        it('keeps the default query (every session) when the draft has no session filter', async () => {
            draftSpy.mockReturnValue([
                200,
                {
                    name: 'Overview',
                    description: 'Summarizes sessions.',
                    scanner_type: 'summarizer',
                    scanner_config: { prompt: 'Summarize the session.' },
                    rationale: '',
                    query: null,
                },
            ])
            router.actions.push(urls.replayVisionScannerTemplate('new'))

            await expectLogic(logic, () =>
                logic.actions.draftScannerFromGoal('what are users doing?')
            ).toFinishAllListeners()

            expect(logic.values.scanner?.query).toEqual({ kind: 'RecordingsQuery' })
        })

        it('drops a stale draft when the user has left the template step mid-request', async () => {
            draftSpy.mockReturnValue([
                200,
                { name: 'Stale', description: '', scanner_type: 'classifier', scanner_config: { prompt: 'x' } },
            ])
            router.actions.push(urls.replayVisionScannerTemplate('new'))
            // Simulate picking a template while the model call is still in flight.
            logic.actions.setScannerValue('name', 'My template pick')
            router.actions.push(urls.replayVisionScannerConfigure('new'))
            const pathBefore = router.values.location.pathname

            await expectLogic(logic, () =>
                logic.actions.draftScannerFromGoal('understand what users come here to do')
            ).toFinishAllListeners()

            expect(logic.values.scanner).toMatchObject({ name: 'My template pick', scanner_type: 'monitor' })
            expect(router.values.location.pathname).toEqual(pathBefore)
        })

        it('keeps the form untouched when drafting fails', async () => {
            draftSpy.mockReturnValue([503, { detail: 'model down' }])
            const pathBefore = router.values.location.pathname

            await expectLogic(logic, () => logic.actions.draftScannerFromGoal('find rage clicks'))
                .toDispatchActions(['draftScannerFromGoalFailure'])
                .toFinishAllListeners()

            expect(logic.values.goalDraft).toBeNull()
            expect(logic.values.scanner).toMatchObject({
                name: 'MockHog App + Marketing monitor',
                scanner_type: 'monitor',
            })
            expect(router.values.location.pathname).toEqual(pathBefore)
        })

        // The in-player analysis nudge hands the goal to the wizard via a one-shot sessionStorage
        // hand-off that authorizes the auto-start; the free text never travels in the URL.
        it('consumes the nudge hand-off: prefills the box and starts the draft with the goal never in the URL', async () => {
            draftSpy.mockReturnValue([
                200,
                { name: 'Rage clicks', description: '', scanner_type: 'monitor', scanner_config: { prompt: 'x' } },
            ])
            markGoalDraftIntent('find rage clicks in checkout')
            router.actions.push(urls.replayVisionScannerTemplate('new'))

            await expectLogic(logic, () => logic.actions.loadScanner())
                .toDispatchActions([
                    logic.actionCreators.setGoalDraftInput('find rage clicks in checkout'),
                    'draftScannerFromGoal',
                ])
                .toFinishAllListeners()

            expect(draftSpy).toHaveBeenCalled()
            expect(router.values.searchParams.goal).toBeUndefined()
            expect(logic.values.scanner).toMatchObject({ name: 'Rage clicks' })
            expect(router.values.location.pathname).toContain(urls.replayVisionScannerDetails('new'))
            // One-shot: the entry consumed the hand-off, so a reload cannot re-fire the draft.
            expect(consumeGoalDraftIntent()).toBeNull()
        })

        // The hand-off is consumed on every wizard entry, even when another prefill path wins,
        // so it can't stay armed for the tab session and auto-start from a later ?goal= link.
        it('an entry that takes the experiment path still consumes the hand-off, so a later ?goal= link cannot auto-start', async () => {
            useMocks({
                get: {
                    '/api/projects/:team/experiments/:id/': () => [200, { id: 7, name: 'Checkout redesign' }],
                },
            })
            markGoalDraftIntent('find rage clicks in checkout')
            router.actions.push(urls.replayVisionScannerTemplate('new'), { experiment: '7' })
            await expectLogic(logic, () => logic.actions.loadScanner()).toFinishAllListeners()

            router.actions.push(urls.replayVisionScannerTemplate('new'), { goal: 'find rage clicks in checkout' })
            await expectLogic(logic, () => logic.actions.loadScanner()).toFinishAllListeners()

            expect(logic.values.goalDraftInput).toEqual('find rage clicks in checkout')
            expect(draftSpy).not.toHaveBeenCalled()
        })

        // Documented precedence with the ?filters= deep link (a fully built query): filters win,
        // the free-text goal is dropped, regardless of which entry point built the URL.
        it('an explicit ?filters= param outranks the goal prefill and drops it', async () => {
            markGoalDraftIntent('find rage clicks in checkout')
            router.actions.push(urls.replayVisionScannerTemplate('new'), {
                filters: JSON.stringify({ kind: 'RecordingsQuery' }),
                goal: 'find rage clicks in checkout',
            })

            await expectLogic(logic, () => logic.actions.loadScanner()).toFinishAllListeners()

            expect(logic.values.goalDraftInput).toEqual('')
            expect(draftSpy).not.toHaveBeenCalled()
        })

        // A ?goal= link without the nudge's marker (e.g. crafted or shared) must not spend the
        // user's AI allowance on its own; it only prefills the box for an explicit click.
        it('a bare ?goal= param prefills the input without auto-starting the draft', async () => {
            router.actions.push(urls.replayVisionScannerTemplate('new'), { goal: 'find rage clicks in checkout' })

            await expectLogic(logic, () => logic.actions.loadScanner()).toFinishAllListeners()

            expect(logic.values.goalDraftInput).toEqual('find rage clicks in checkout')
            expect(draftSpy).not.toHaveBeenCalled()
            expect(router.values.searchParams.goal).toBeUndefined()
        })

        // The drafted scanner persists over the sole saved-draft slot, so auto-starting on top of
        // a restored draft would destroy the user's saved work without any action of theirs.
        it('a nudge hand-off over a saved draft restores the draft and does not auto-start', async () => {
            writeScannerDraft(MOCK_TEAM_ID, {
                ...logic.values.scanner!,
                name: 'My saved work',
            })
            markGoalDraftIntent('find rage clicks in checkout')
            router.actions.push(urls.replayVisionScannerTemplate('new'))

            await expectLogic(logic, () => logic.actions.loadScanner()).toFinishAllListeners()

            expect(logic.values.scanner).toMatchObject({ name: 'My saved work' })
            expect(logic.values.goalDraftInput).toEqual('find rage clicks in checkout')
            expect(draftSpy).not.toHaveBeenCalled()
        })
    })

    describe('setScannerType', () => {
        it.each([
            { type: 'monitor' as const, expectedConfig: { prompt: '' } },
            { type: 'summarizer' as const, expectedConfig: { prompt: '', length: 'medium' } },
            { type: 'classifier' as const, expectedConfig: { prompt: '', tags: [], multi_label: true } },
            { type: 'scorer' as const, expectedConfig: { prompt: '', scale: { min: 0, max: 10 } } },
        ])(
            'switching to $type replaces scanner_config with the default for that type',
            async ({ type, expectedConfig }) => {
                await expectLogic(logic, () => logic.actions.setScannerType(type)).toMatchValues({
                    scanner: expect.objectContaining({ scanner_type: type, scanner_config: expectedConfig }),
                })
            }
        )

        it('does not preserve old prompt across type changes', async () => {
            logic.actions.setScannerValues({ scanner_config: { prompt: 'Was there a refund?' } })
            await expectLogic(logic, () => logic.actions.setScannerType('summarizer')).toMatchValues({
                scanner: expect.objectContaining({
                    scanner_config: { prompt: '', length: 'medium' },
                }),
            })
        })

        it('clears the showScannerErrors flag so stale validation does not bleed into the new type', async () => {
            logic.actions.submitScanner()
            await expectLogic(logic).toMatchValues({ showScannerErrors: true })
            logic.actions.setScannerType('summarizer')
            await expectLogic(logic).toMatchValues({ showScannerErrors: false })
        })
    })

    describe('appendClassifierTags', () => {
        it('merges suggested tags into the vocabulary, deduping case-insensitively and trimming', async () => {
            logic.actions.setScannerType('classifier')
            logic.actions.setScannerValues({
                scanner_config: {
                    prompt: 'Categorize intent',
                    tags: ['checkout', 'pricing'],
                    multi_label: true,
                } as ClassifierScanner['scanner_config'],
            })
            await expectLogic(logic, () => {
                logic.actions.appendClassifierTags(['Checkout', '  billing ', 'pricing', '', 'account'])
            }).toMatchValues({
                scanner: expect.objectContaining({
                    scanner_config: expect.objectContaining({ tags: ['checkout', 'pricing', 'billing', 'account'] }),
                }),
            })
        })

        it('is a no-op for non-classifier scanners', async () => {
            // Default scanner is a monitor — appending classifier tags must not add a tags field.
            await expectLogic(logic, () => logic.actions.appendClassifierTags(['x'])).toMatchValues({
                scanner: expect.objectContaining({ scanner_type: 'monitor', scanner_config: { prompt: '' } }),
            })
        })
    })

    describe('clearClassifierTags', () => {
        it('empties the categories of a classifier scanner', async () => {
            logic.actions.setScannerType('classifier')
            logic.actions.setScannerValues({
                scanner_config: {
                    prompt: 'Categorize intent',
                    tags: ['checkout', 'pricing'],
                    multi_label: true,
                } as ClassifierScanner['scanner_config'],
            })
            await expectLogic(logic, () => logic.actions.clearClassifierTags()).toMatchValues({
                scanner: expect.objectContaining({
                    scanner_config: expect.objectContaining({ tags: [] }),
                }),
            })
        })

        it('is a no-op for non-classifier scanners', async () => {
            // Default scanner is a monitor, so clearing must not add a tags field to its config.
            await expectLogic(logic, () => logic.actions.clearClassifierTags()).toMatchValues({
                scanner: expect.objectContaining({ scanner_type: 'monitor', scanner_config: { prompt: '' } }),
            })
        })
    })

    describe('tag suggestions', () => {
        const setupClassifier = (): void => {
            logic.actions.setScannerType('classifier')
            logic.actions.setScannerValues({
                scanner_config: {
                    prompt: 'Categorize intent',
                    tags: ['pricing'],
                    multi_label: true,
                } as ClassifierScanner['scanner_config'],
            })
        }

        it('loads grounded suggestions from the endpoint', async () => {
            suggestSpy.mockReturnValueOnce([
                200,
                { suggestions: [{ tag: 'abandoned_checkout', rationale: 'seen 12x', source: 'observed' }] },
            ])
            setupClassifier()
            await expectLogic(logic, () => logic.actions.loadTagSuggestions())
                .toDispatchActions(['loadTagSuggestionsSuccess'])
                .toMatchValues({
                    tagSuggestions: [{ tag: 'abandoned_checkout', rationale: 'seen 12x', source: 'observed' }],
                    tagSuggestionsLoading: false,
                })
        })

        it('accepting a suggestion adds it to the vocabulary and drops it from the panel', async () => {
            suggestSpy.mockReturnValueOnce([
                200,
                {
                    suggestions: [
                        { tag: 'abandoned_checkout', rationale: 'r', source: 'observed' },
                        { tag: 'pricing_confusion', rationale: 'r', source: 'product' },
                    ],
                },
            ])
            setupClassifier()
            await expectLogic(logic, () => logic.actions.loadTagSuggestions()).toDispatchActions([
                'loadTagSuggestionsSuccess',
            ])
            await expectLogic(logic, () => logic.actions.acceptTagSuggestion('abandoned_checkout'))
                .toFinishAllListeners()
                .toMatchValues({
                    scanner: expect.objectContaining({
                        scanner_config: expect.objectContaining({ tags: ['pricing', 'abandoned_checkout'] }),
                    }),
                    tagSuggestions: [{ tag: 'pricing_confusion', rationale: 'r', source: 'product' }],
                })
        })

        it('accept all adds every suggestion and clears the panel', async () => {
            suggestSpy.mockReturnValueOnce([
                200,
                {
                    suggestions: [
                        { tag: 'rage_clicking', rationale: 'r', source: 'observed' },
                        { tag: 'form_errors', rationale: 'r', source: 'product' },
                    ],
                },
            ])
            setupClassifier()
            await expectLogic(logic, () => logic.actions.loadTagSuggestions()).toDispatchActions([
                'loadTagSuggestionsSuccess',
            ])
            await expectLogic(logic, () => logic.actions.acceptAllTagSuggestions())
                .toFinishAllListeners()
                .toMatchValues({
                    scanner: expect.objectContaining({
                        scanner_config: expect.objectContaining({ tags: ['pricing', 'rage_clicking', 'form_errors'] }),
                    }),
                    tagSuggestions: [],
                })
        })
    })

    describe('submit intent', () => {
        it('advance intent routes to /triggers without calling the API', async () => {
            router.actions.push('/replay-vision/new/configure')
            logic.actions.setScannerValues({
                name: 'Test scanner',
                scanner_config: { prompt: 'Q?' },
            })
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            expect(router.values.location.pathname).toContain('/replay-vision/new/triggers')
        })

        it('advance does not mark the draft as saved, so the unsaved-changes guard stays armed', async () => {
            router.actions.push('/replay-vision/new/configure')
            logic.actions.setScannerValues({ name: 'Draft scanner', scanner_config: { prompt: 'Q?' } })
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            // The draft must not be adopted as the saved baseline — no API write happened.
            expect(logic.values.originalScanner?.name).toBe('MockHog App + Marketing monitor')
            expect(logic.values.hasUnsavedChanges).toBe(true)
        })

        it('default-intent submit (Enter) on the new-scanner configure step advances instead of creating', async () => {
            router.actions.push('/replay-vision/new/configure')
            logic.actions.setScannerValues({ name: 'Test scanner', scanner_config: { prompt: 'Q?' } })
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            expect(createSpy).not.toHaveBeenCalled()
            expect(router.values.location.pathname).toContain('/replay-vision/new/triggers')
        })

        it('keeps the ?template param when advancing, so the type stays fixed to the template', async () => {
            router.actions.push(`${urls.replayVisionScannerConfigure('new')}?template=dead_end`)
            logic.actions.setScannerValues({ name: 'Test scanner', scanner_config: { prompt: 'Q?' } })
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            expect(router.values.location.pathname).toContain('/replay-vision/new/triggers')
            expect(router.values.searchParams.template).toEqual('dead_end')
        })

        it('advances from the step the editor scene reports, even when the URL matches no step', async () => {
            router.actions.push('/replay-vision/new/not-a-step')
            scannerEditorSceneLogic.actions.setStep('configure')
            logic.actions.setScannerValues({ name: 'Test scanner', scanner_config: { prompt: 'Q?' } })
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            expect(router.values.location.pathname).toContain('/replay-vision/new/triggers')
        })

        it('routes a rejected submit to the step that renders the errored fields', async () => {
            // Defaults leave name and prompt empty, both configure-owned.
            router.actions.push('/replay-vision/new/triggers')
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            expect(createSpy).not.toHaveBeenCalled()
            expect(router.values.location.pathname).toContain('/replay-vision/new/configure')
        })

        it('submitting the final step creates the scanner, lands on it, and announces the first scan', async () => {
            const success = jest.spyOn(lemonToast, 'success')
            router.actions.push('/replay-vision/new/budget')
            scannerEditorSceneLogic.actions.setStep('budget')
            logic.actions.setScannerValues({ name: 'Test scanner', scanner_config: { prompt: 'Q?' } })
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            expect(createSpy).toHaveBeenCalledTimes(1)
            expect(router.values.location.pathname).toContain('/replay-vision/created-scanner')
            // The toast must tell the same story as the Overview's first-scan pending panel.
            expect(success).toHaveBeenCalledWith(
                'Scanner created. First scan in progress.',
                expect.objectContaining({ button: expect.objectContaining({ label: 'Scan a recording now' }) })
            )
        })
    })

    describe('new scanner draft', () => {
        beforeEach(() => {
            teamLogic.mount()
        })

        it('restores drafted values when the wizard remounts, still diverging from the saved scanner', async () => {
            logic.actions.setScannerValues({ name: 'Half done', scanner_config: { prompt: 'Find rage clicks' } })
            logic.unmount()
            logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.scanner?.name).toBe('Half done')
            expect(logic.values.hasUnsavedChanges).toBe(true)
        })

        it('restores an on-but-empty credit limit across a remount, so the save stays blocked', async () => {
            logic.actions.setScannerValues({ credit_limit_enabled: true, credit_limit: null })
            logic.unmount()
            logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.creditLimitState).toMatchObject({ limit: null, isOn: true })
            expect(logic.values.scannerValidationErrors).toMatchObject({
                credit_limit: 'Enter a credit limit, or turn the limit off',
            })
        })

        it.each([
            ['scannerSaved', () => logic.actions.scannerSaved(logic.values.scanner!)],
            ['startFromTemplate', () => logic.actions.startFromTemplate(null)],
            ['discardScannerDraft', () => logic.actions.discardScannerDraft()],
        ])('clears the draft on %s', async (_label, act) => {
            const teamId = teamLogic.values.currentTeamId!
            logic.actions.setScannerValues({ name: 'Drafted' })
            expect(readScannerDraft(teamId)?.scanner.name).toBe('Drafted')
            act()
            expect(readScannerDraft(teamId)).toBeNull()
        })

        it('persists a type switch, so a reload does not restore the old type', async () => {
            const teamId = teamLogic.values.currentTeamId!
            logic.actions.setScannerValues({ name: 'Drafted' })
            logic.actions.setScannerType('summarizer')
            expect(readScannerDraft(teamId)?.scanner.scanner_type).toBe('summarizer')
        })

        it('keeps the draft on resetScanner, so leaving the editor stays resumable', async () => {
            const teamId = teamLogic.values.currentTeamId!
            logic.actions.setScannerValues({ name: 'Drafted' })
            logic.actions.resetScanner()
            expect(readScannerDraft(teamId)?.scanner.name).toBe('Drafted')
        })

        it('preserves an existing draft when the wizard is entered from an experiment deep link', async () => {
            // A deep link prefills a fresh scanner but must not wipe the draft the user already has;
            // the prefill runs under restoringDraft so persistDraft can't clear it.
            useMocks({
                get: {
                    '/api/projects/:team/experiments/:id/': () => [200, { id: 7, name: 'Checkout redesign' }],
                },
            })
            const teamId = teamLogic.values.currentTeamId!
            logic.actions.setScannerValues({ name: 'Drafted' })
            expect(readScannerDraft(teamId)?.scanner.name).toBe('Drafted')
            logic.unmount()

            router.actions.push(urls.replayVisionScannerConfigure('new'), { experiment: '7' })
            logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            expect(readScannerDraft(teamId)?.scanner.name).toBe('Drafted')
        })

        it('discards back to the loaded baseline, so the leave guard stays disarmed', async () => {
            router.actions.push(urls.replayVisionScannerTemplate('new'), { template: 'dead_end' })
            logic.unmount()
            logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            const baseline = logic.values.scanner!.name

            logic.actions.setScannerValues({ name: 'Drafted' })
            logic.actions.discardScannerDraft()
            expect(logic.values.scanner!.name).toBe(baseline)
            expect(logic.values.hasUnsavedChanges).toBe(false)
        })

        it('does not restamp the draft when restoring it, so it still ages out', async () => {
            const teamId = teamLogic.values.currentTeamId!
            logic.actions.setScannerValues({ name: 'Half done' })
            const savedAt = readScannerDraft(teamId)!.savedAt
            logic.unmount()
            logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(readScannerDraft(teamId)!.savedAt).toBe(savedAt)
        })

        it('announces the draft on the way out, once an edit has been saved', async () => {
            const info = jest.spyOn(lemonToast, 'info')
            logic.actions.setScannerValues({ name: 'Drafted' })
            logic.unmount()
            expect(info).toHaveBeenCalledWith(
                'Draft saved',
                expect.objectContaining({ button: expect.objectContaining({ label: 'Resume' }) })
            )
            info.mockRestore()
        })

        // Leaving mid-wizard is routine (the recordings step links out to settings), so resuming has to
        // land where the work was. Always returning to the first step reads as having lost the later ones.
        it('resumes on the step the last edit was made on', async () => {
            const info = jest.spyOn(lemonToast, 'info')
            const editorLogic = scannerEditorSceneLogic()
            editorLogic.mount()
            try {
                editorLogic.actions.setStep('budget')
                logic.actions.setScannerValues({ name: 'Drafted' })
                logic.unmount()

                info.mock.calls[0][1]?.button?.action?.()
                expect(router.values.location.pathname).toContain(urls.replayVisionScannerBudget('new'))
            } finally {
                info.mockRestore()
                editorLogic.unmount()
                router.actions.push(urls.replayVision())
            }
        })

        it('stays quiet on the way out when the draft was only restored', async () => {
            logic.actions.setScannerValues({ name: 'Drafted' })
            logic.unmount()
            logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            const info = jest.spyOn(lemonToast, 'info')
            logic.unmount()
            expect(info).not.toHaveBeenCalled()
            info.mockRestore()
        })

        it('clears a resumed draft when its edits are undone back to the starting point', async () => {
            const teamId = teamLogic.values.currentTeamId!
            const original = logic.values.scanner!.name
            logic.actions.setScannerValues({ name: 'Drafted' })
            logic.unmount()
            logic = replayScannerLogic({ id: 'new' })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            logic.actions.setScannerValues({ name: original })
            expect(readScannerDraft(teamId)).toBeNull()
        })
    })

    describe('validation errors', () => {
        it.each([
            {
                name: 'flags missing prompt',
                setup: () => undefined,
                expectedErrors: { scanner_config: expect.objectContaining({ prompt: 'Prompt is required' }) },
            },
            {
                name: 'flags sampling rate outside (0, 1]',
                setup: () => logic.actions.setScannerValues({ sampling_rate: 0 }),
                expectedErrors: { sampling_rate: expect.any(String) },
            },
            {
                name: 'flags a zero credit limit, which would silently stop the scanner forever',
                setup: () => logic.actions.setScannerValues({ credit_limit: 0 }),
                expectedErrors: { credit_limit: expect.any(String) },
            },
            {
                name: 'flags a negative credit limit',
                setup: () => logic.actions.setScannerValues({ credit_limit: -10 }),
                expectedErrors: { credit_limit: expect.any(String) },
            },
            {
                name: 'flags a credit limit above the API int4 bound, which the server would reject',
                setup: () => logic.actions.setScannerValues({ credit_limit: 2147483648 }),
                expectedErrors: { credit_limit: expect.any(String) },
            },
            {
                name: 'flags the limit toggled on but left empty, so it cannot silently save as unlimited',
                setup: () => logic.actions.setScannerValues({ credit_limit_enabled: true, credit_limit: null }),
                expectedErrors: { credit_limit: expect.any(String) },
            },
            {
                name: 'flags scorer scale when min >= max',
                setup: () => {
                    logic.actions.setScannerType('scorer')
                    logic.actions.setScannerValues({
                        scanner_config: {
                            prompt: 'rate this',
                            scale: { min: 10, max: 5 },
                        } as ScorerScanner['scanner_config'],
                    })
                },
                expectedErrors: {
                    scanner_config: expect.objectContaining({ scale: expect.stringContaining('greater than') }),
                },
            },
            {
                name: 'flags scorer scale when min is not a finite number',
                setup: () => {
                    logic.actions.setScannerType('scorer')
                    logic.actions.setScannerValues({
                        scanner_config: {
                            prompt: 'rate this',
                            scale: { min: Number.NaN, max: 10 },
                        } as ScorerScanner['scanner_config'],
                    })
                },
                expectedErrors: {
                    scanner_config: expect.objectContaining({ scale: expect.stringContaining('numbers') }),
                },
            },
            {
                name: 'flags classifier with empty tag vocabulary',
                setup: () => {
                    logic.actions.setScannerType('classifier')
                    logic.actions.setScannerValues({
                        scanner_config: {
                            prompt: 'tag this',
                            tags: [],
                            multi_label: true,
                        } as ClassifierScanner['scanner_config'],
                    })
                },
                expectedErrors: {
                    scanner_config: expect.objectContaining({ tags: expect.stringContaining('at least one category') }),
                },
            },
            {
                name: 'flags classifier with duplicate tags',
                setup: () => {
                    logic.actions.setScannerType('classifier')
                    logic.actions.setScannerValues({
                        scanner_config: {
                            prompt: 'tag this',
                            tags: ['Bug', 'bug'],
                            multi_label: true,
                        } as ClassifierScanner['scanner_config'],
                    })
                },
                expectedErrors: {
                    scanner_config: expect.objectContaining({ tags: 'Categories must be unique' }),
                },
            },
            {
                name: 'flags classifier with blank/whitespace tags',
                setup: () => {
                    logic.actions.setScannerType('classifier')
                    logic.actions.setScannerValues({
                        scanner_config: {
                            prompt: 'tag this',
                            tags: ['bug', '   '],
                            multi_label: true,
                        } as ClassifierScanner['scanner_config'],
                    })
                },
                expectedErrors: {
                    scanner_config: expect.objectContaining({ tags: "Categories can't be blank" }),
                },
            },
        ])('$name', async ({ setup, expectedErrors }) => {
            setup()
            await expectLogic(logic).toMatchValues({
                scannerValidationErrors: expect.objectContaining(expectedErrors),
            })
        })

        it('passes when all required fields are filled', async () => {
            logic.actions.setScannerType('classifier')
            logic.actions.setScannerValues({
                name: 'My scanner',
                sampling_rate: 0.1,
                scanner_config: {
                    prompt: 'Categorize',
                    tags: ['a'],
                    multi_label: true,
                } as ClassifierScanner['scanner_config'],
            })
            await expectLogic(logic).toMatchValues({
                isScannerValid: true,
            })
        })

        // 2147483647 is the API's int4 bound, the highest value the server accepts.
        it.each([null, 1, 500, 2147483647])(
            'accepts a credit limit of %p, including the unlimited default',
            async (limit) => {
                logic.actions.setScannerValues({ credit_limit: limit })
                await expectLogic(logic).toMatchValues({
                    scannerValidationErrors: expect.objectContaining({ credit_limit: undefined }),
                })
            }
        )
    })

    describe('creditLimitState', () => {
        const estimate = (perMonth: number | null, perObservation = 15): void => {
            logic.actions.loadScannerEstimateSuccess({
                estimated_credits_per_month: perMonth,
                credits_per_observation: perObservation,
            } as any)
        }

        it('decodes null as limit off', async () => {
            logic.actions.setScannerValues({ credit_limit: null })
            await expectLogic(logic).toMatchValues({
                creditLimitState: expect.objectContaining({ limit: null, isOn: false }),
            })
        })

        it('keeps the toggle on while the amount is still empty, which blocks the save', async () => {
            logic.actions.setScannerValues({ credit_limit_enabled: true, credit_limit: null })
            await expectLogic(logic).toMatchValues({
                creditLimitState: expect.objectContaining({ limit: null, isOn: true }),
            })
        })

        it('derives the toggle for scanners that never carried the form-only field', async () => {
            // API-loaded scanners have no credit_limit_enabled; a set limit must still present as on.
            logic.actions.setScannerValues({ credit_limit_enabled: undefined, credit_limit: 250 })
            await expectLogic(logic).toMatchValues({
                creditLimitState: expect.objectContaining({ limit: 250, isOn: true }),
            })
        })

        it('seeds the field with double the forecast when one exists', async () => {
            estimate(100)
            await expectLogic(logic).toMatchValues({
                creditLimitState: expect.objectContaining({ seedValue: 200 }),
            })
        })

        it('seeds at least one credit for a tiny but non-zero forecast', async () => {
            estimate(0.3)
            await expectLogic(logic).toMatchValues({
                creditLimitState: expect.objectContaining({ seedValue: 1 }),
            })
        })

        it.each([
            ['no estimate', null],
            ['a zero estimate, which must not seed a 1-credit cap', 0],
        ])('leaves the field empty with %s', async (_name, perMonth) => {
            estimate(perMonth as number | null)
            await expectLogic(logic).toMatchValues({
                creditLimitState: expect.objectContaining({ seedValue: null }),
            })
        })

        it('flags a limit below the forecast and one below a single scan', async () => {
            estimate(100, 15)
            logic.actions.setScannerValues({ credit_limit_enabled: true, credit_limit: 10 })
            await expectLogic(logic).toMatchValues({
                creditLimitState: expect.objectContaining({
                    limit: 10,
                    isOn: true,
                    isBelowEstimate: true,
                    cannotAffordOneScan: true,
                }),
            })
        })
    })

    describe('credit limit on a loaded scanner', () => {
        // API scanners never carry the form-only credit_limit_enabled field.
        const loadedScanner = {
            id: 'limited-1',
            name: 'Limited scanner',
            enabled: true,
            scanner_type: 'monitor',
            scanner_config: { prompt: 'Anything odd?' },
            sampling_rate: 1,
            credit_limit: 500,
        }
        let editLogic: ReturnType<typeof replayScannerLogic.build>

        beforeEach(() => {
            useMocks({
                get: { '/api/projects/:team/vision/scanners/:id/': () => [200, loadedScanner] },
            })
            editLogic = replayScannerLogic({ id: 'limited-1' })
            editLogic.mount()
        })

        afterEach(() => {
            editLogic?.unmount()
        })

        it('blocks the save when the amount is cleared, instead of silently saving as unlimited', async () => {
            await expectLogic(editLogic, () => editLogic.actions.loadScanner()).toFinishAllListeners()
            expect(editLogic.values.scanner.credit_limit_enabled).toBe(true)
            // A bare amount clear, without the toggle write the editor card sends alongside it.
            editLogic.actions.setScannerValues({ credit_limit: null })
            await expectLogic(editLogic).toMatchValues({
                creditLimitState: expect.objectContaining({ limit: null, isOn: true }),
                scannerValidationErrors: expect.objectContaining({
                    credit_limit: 'Enter a credit limit, or turn the limit off',
                }),
            })
        })

        it('Enter on the details step advances rather than failing validation on unseen fields', async () => {
            // A from-scratch scanner has an empty prompt, which only the configure step can fix.
            router.actions.push(urls.replayVisionScannerDetails('new'))
            scannerEditorSceneLogic.actions.setStep('details')
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            expect(router.values.location.pathname).toContain(urls.replayVisionScannerConfigure('new'))
        })

        it('keeps the ?template param when a rejected submit jumps to the errored step', async () => {
            router.actions.push(`${urls.replayVisionScannerTriggers('new')}?template=dead_end`)
            scannerEditorSceneLogic.actions.setStep('triggers')
            logic.actions.setScannerValues({ scanner_config: { prompt: '' } })
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            expect(router.values.location.pathname).toContain(urls.replayVisionScannerConfigure('new'))
            expect(router.values.searchParams.template).toEqual('dead_end')
        })

        it('Enter on an intermediate step advances instead of saving and leaving the wizard', async () => {
            await expectLogic(editLogic, () => editLogic.actions.loadScanner()).toFinishAllListeners()
            router.actions.push(urls.replayVisionScannerDetails('limited-1'))
            await expectLogic(editLogic, () => editLogic.actions.submitScanner()).toFinishAllListeners()
            expect(router.values.location.pathname).toContain(urls.replayVisionScannerConfigure('limited-1'))
        })

        it('strips the form-only toggle from the update payload', async () => {
            let patchedBody: any
            useMocks({
                patch: {
                    '/api/projects/:team/vision/scanners/:id/': async ({ request }: { request: Request }) => {
                        patchedBody = await request.json()
                        return [200, loadedScanner]
                    },
                },
            })
            await expectLogic(editLogic, () => editLogic.actions.loadScanner()).toFinishAllListeners()
            // Only the final step persists; earlier ones advance, so save from where the button lives.
            router.actions.push(urls.replayVisionScannerBudget('sid'))
            editLogic.actions.setScannerValues({ credit_limit_enabled: true, credit_limit: 100 })
            await expectLogic(editLogic, () => editLogic.actions.submitScanner()).toDispatchActions(['scannerSaved'])
            expect(patchedBody.credit_limit).toBe(100)
            expect(patchedBody).not.toHaveProperty('credit_limit_enabled')
        })
    })

    describe('buildObservationListParams', () => {
        const monitorScanner = { scanner_type: 'monitor' } as ReplayScanner
        const scorerScanner = { scanner_type: 'scorer' } as ReplayScanner
        const classifierScanner = { scanner_type: 'classifier' } as ReplayScanner
        const emptyValues = {
            observationStatusFilter: [] as ObservationStatusValue[],
            observationTriggeredByFilter: [] as ObservationTriggeredByValue[],
            observationVerdictFilter: [] as ObservationVerdictValue[],
            observationTagFilter: [] as string[],
            observationMinScoreFilter: null as number | null,
            observationMaxScoreFilter: null as number | null,
            observationSubjectFilter: '',
            observationDateFrom: null as string | null,
            observationDateTo: null as string | null,
            observationBackfillFilter: null as string | null,
            observationsSort: null,
            scanner: null,
        }

        it('returns empty params when no filters, sort, or pagination', () => {
            expect(buildObservationListParams({ ...emptyValues })).toEqual({})
        })

        it('passes the backfill filter as backfill_id', () => {
            expect(buildObservationListParams({ ...emptyValues, observationBackfillFilter: 'bf-1' })).toEqual({
                backfill_id: 'bf-1',
            })
        })

        it('passes limit and offset only when offset is positive', () => {
            expect(buildObservationListParams({ ...emptyValues }, 50, 0)).toEqual({ limit: 50 })
            expect(buildObservationListParams({ ...emptyValues }, 50, 100)).toEqual({ limit: 50, offset: 100 })
        })

        it('CSV-joins each filter array', () => {
            const params = buildObservationListParams({
                ...emptyValues,
                observationStatusFilter: ['failed', 'succeeded'],
                observationTriggeredByFilter: ['on_demand'],
                observationVerdictFilter: ['yes', 'inconclusive'],
                observationTagFilter: ['onboarding', 'support'],
            })
            expect(params.status).toBe('failed,succeeded')
            expect(params.triggered_by).toBe('on_demand')
            expect(params.verdict).toBe('yes,inconclusive')
            expect(params.tags).toBe('onboarding,support')
        })

        it('passes score bounds only when set, including a zero bound', () => {
            expect(buildObservationListParams({ ...emptyValues, observationMinScoreFilter: 7 })).toEqual({
                min_score: 7,
            })
            expect(
                buildObservationListParams({
                    ...emptyValues,
                    observationMinScoreFilter: 0,
                    observationMaxScoreFilter: 3.5,
                })
            ).toEqual({ min_score: 0, max_score: 3.5 })
        })

        it('passes date range only when set', () => {
            const params = buildObservationListParams({
                ...emptyValues,
                observationDateFrom: '-7d',
                observationDateTo: '2026-07-01',
            })
            expect(params).toEqual({ date_from: '-7d', date_to: '2026-07-01' })
        })

        it.each<[ReplayScanner, string]>([
            [scorerScanner, 'result_score'],
            [monitorScanner, 'result_verdict'],
        ])('maps Result column for %p to %s', (scanner, expected) => {
            const params = buildObservationListParams({
                ...emptyValues,
                scanner,
                observationsSort: { columnKey: 'result', order: 1 },
            })
            expect(params.order_by).toBe(expected)
        })

        it('omits order_by for Result column when scanner type has no sortable result', () => {
            const params = buildObservationListParams({
                ...emptyValues,
                scanner: classifierScanner,
                observationsSort: { columnKey: 'result', order: 1 },
            })
            expect(params.order_by).toBeUndefined()
        })

        it('prefixes order_by with a minus sign for descending sort', () => {
            const params = buildObservationListParams({
                ...emptyValues,
                observationsSort: { columnKey: 'created_at', order: -1 },
            })
            expect(params.order_by).toBe('-created_at')
        })

        it('maps version column to scanner_version', () => {
            const params = buildObservationListParams({
                ...emptyValues,
                observationsSort: { columnKey: 'version', order: 1 },
            })
            expect(params.order_by).toBe('scanner_version')
        })

        it('passes recording_subject trimmed when set', () => {
            const params = buildObservationListParams({ ...emptyValues, observationSubjectFilter: '  acme  ' })
            expect(params.recording_subject).toBe('acme')
        })

        it('maps recording_subject column to recording_subject_email', () => {
            const params = buildObservationListParams({
                ...emptyValues,
                observationsSort: { columnKey: 'recording_subject', order: 1 },
            })
            expect(params.order_by).toBe('recording_subject_email')
        })
    })

    describe('parseSortParam', () => {
        it('returns null for empty/undefined inputs', () => {
            expect(parseSortParam(undefined)).toBeNull()
            expect(parseSortParam('')).toBeNull()
        })

        it('parses ascending and descending sort tokens', () => {
            expect(parseSortParam('result')).toEqual({ columnKey: 'result', order: 1 })
            expect(parseSortParam('-created_at')).toEqual({ columnKey: 'created_at', order: -1 })
        })

        it('returns null when only a minus sign is supplied', () => {
            expect(parseSortParam('-')).toBeNull()
        })
    })

    describe('parseCsvParam', () => {
        it('returns an empty array for empty/undefined inputs', () => {
            expect(parseCsvParam(undefined)).toEqual([])
            expect(parseCsvParam('')).toEqual([])
        })

        it('splits, trims, and drops empty values', () => {
            expect(parseCsvParam('a, b ,c,')).toEqual(['a', 'b', 'c'])
        })

        it('survives the router coercing a single numeric param to a number', () => {
            expect(parseCsvParam(2024)).toEqual(['2024'])
        })

        it('drops values outside the allowlist when one is given', () => {
            expect(parseCsvParam('banana,yes', ['yes', 'no'])).toEqual(['yes'])
        })
    })

    describe('parseNumericParam', () => {
        it.each([
            [undefined, null],
            // Number('') is 0, so an absent bound must be rejected before the cast.
            ['', null],
            ['   ', null],
            ['abc', null],
            ['0', 0],
            ['3.5', 3.5],
            [7, 7],
        ])('parses %p as %p', (input, expected) => {
            expect(parseNumericParam(input)).toBe(expected)
        })
    })

    describe('observationsPage / sort URL sync', () => {
        let scannedLogic: ReturnType<typeof replayScannerLogic.build>

        beforeEach(() => {
            useMocks({
                get: {
                    '/api/projects/:team/vision/scanners/:id/': () => [
                        200,
                        {
                            id: 'sid',
                            name: 'm',
                            scanner_type: 'monitor',
                            scanner_config: { prompt: 'p' },
                            sampling_rate: 1,
                            enabled: true,
                        },
                    ],
                    '/api/projects/:team/vision/scanners/:id/observations/': { results: [], count: 0 },
                    '/api/projects/:team/vision/scanners/:id/observations/stats/': {
                        status_counts: {
                            total: 0,
                            succeeded: 0,
                            failed: 0,
                            ineligible: 0,
                            in_flight: 0,
                            success_rate: null,
                        },
                        coverage: { recent_sessions: 0, total_sessions: 0, recent_days: 14 },
                        available_tags: [],
                        monitor: null,
                        classifier: null,
                        scorer: null,
                    },
                },
            })
            scannedLogic = replayScannerLogic({ id: 'sid' })
            scannedLogic.mount()
        })

        afterEach(() => {
            scannedLogic?.unmount()
        })

        it('changing the page resets to 1 when the user changes a filter', async () => {
            scannedLogic.actions.setObservationsPage(5)
            expect(scannedLogic.values.observationsPage).toBe(5)
            await expectLogic(scannedLogic, () => {
                scannedLogic.actions.setObservationStatusFilter(['failed'])
            }).toMatchValues({ observationsPage: 1 })
        })

        it('changing sort resets page back to 1', async () => {
            scannedLogic.actions.setObservationsPage(3)
            await expectLogic(scannedLogic, () => {
                scannedLogic.actions.setObservationsSort({ columnKey: 'created_at', order: 1 })
            }).toMatchValues({ observationsPage: 1 })
        })

        it('writes non-default state into the URL search params', async () => {
            await expectLogic(scannedLogic, () => {
                scannedLogic.actions.setObservationStatusFilter(['failed', 'succeeded'])
                scannedLogic.actions.setObservationsPage(3)
            }).toFinishAllListeners()
            expect(router.values.searchParams.status).toBe('failed,succeeded')
            expect(String(router.values.searchParams.page)).toBe('3')
        })

        it('round-trips score bounds through the URL without swapping min and max', async () => {
            await expectLogic(scannedLogic, () => {
                scannedLogic.actions.setObservationScoreRange(3, 8)
            }).toFinishAllListeners()
            expect(String(router.values.searchParams.min_score)).toBe('3')
            expect(String(router.values.searchParams.max_score)).toBe('8')

            router.actions.push(urls.replayVision('sid'), { min_score: 7, max_score: 9 })
            await expectLogic(scannedLogic).toFinishAllListeners()
            expect(scannedLogic.values.observationMinScoreFilter).toBe(7)
            expect(scannedLogic.values.observationMaxScoreFilter).toBe(9)
        })

        it('drops default state from the URL', async () => {
            await expectLogic(scannedLogic, () => {
                scannedLogic.actions.setObservationsPage(1)
                scannedLogic.actions.setObservationsSort({ columnKey: 'created_at', order: -1 })
            }).toFinishAllListeners()
            expect(router.values.searchParams.page).toBeUndefined()
            expect(router.values.searchParams.sort).toBeUndefined()
        })
    })

    describe('hasUnsavedChanges', () => {
        it('is false when no original scanner is loaded', () => {
            expect(logic.values.hasUnsavedChanges).toBe(false)
        })

        it('is false when current matches original', async () => {
            logic.actions.loadScannerSuccess({
                ...logic.values.scanner!,
                id: 'abc',
                name: 'Loaded',
            })
            await expectLogic(logic).toMatchValues({ hasUnsavedChanges: false })
        })

        it('is true after a form edit', async () => {
            logic.actions.loadScannerSuccess({
                ...logic.values.scanner!,
                id: 'abc',
                name: 'Loaded',
            })
            await expectLogic(logic, () => logic.actions.setScannerValues({ name: 'Edited' })).toMatchValues({
                hasUnsavedChanges: true,
            })
        })
    })

    describe('scannerWatermarkRefreshed', () => {
        // Guards the background watermark refresh against regressing to the full loadScannerSuccess
        // path, which resets the form from the server and refires the observation loads.
        it('advances the sweep watermark without resetting form edits or reloading observations', async () => {
            logic.actions.loadScannerSuccess({ ...logic.values.scanner!, id: 'abc', name: 'Loaded' })
            logic.actions.setScannerValues({ name: 'Edited' })

            const refreshed = { ...logic.values.scanner!, name: 'Loaded', last_swept_at: '2026-08-13T10:00:00Z' }
            // toDispatchActions moves the history pointer past the setup's own setScannerValues first.
            await expectLogic(logic, () => logic.actions.scannerWatermarkRefreshed(refreshed))
                .toDispatchActions(['scannerWatermarkRefreshed'])
                .toNotHaveDispatchedActions(['setScannerValues', 'loadObservations', 'loadObservationStats'])
            expect(logic.values.scanner?.name).toBe('Edited')
            expect(logic.values.scanner?.last_swept_at).toBe('2026-08-13T10:00:00Z')
        })
    })

    describe('shouldGuardScannerNavigation', () => {
        const scannerId = 'abc-123'
        const configure = urls.replayVisionScannerConfigure(scannerId)
        const triggers = urls.replayVisionScannerTriggers(scannerId)
        const template = urls.replayVisionScannerTemplate(scannerId)
        const selfDriving = urls.replayVisionScannerSelfDriving(scannerId)
        const detail = urls.replayVision(scannerId)
        const base = {
            hasUnsavedChanges: true,
            isSubmitting: false,
            hasSavedDraft: false,
            scannerId,
            currentPathname: configure,
        }

        it.each([
            // Nothing to lose, or the editor is mid-submit (save / step advance redirects itself).
            ['no unsaved changes', { ...base, hasUnsavedChanges: false, nextPathname: '/insights' }, false],
            ['mid-submit redirect to detail', { ...base, isSubmitting: true, nextPathname: detail }, false],
            ['edits already saved as a draft', { ...base, hasSavedDraft: true, nextPathname: '/insights' }, false],
            // Moving between the wizard's own steps keeps the same draft mounted.
            ['forward to triggers step', { ...base, nextPathname: triggers }, false],
            ['back to template step', { ...base, currentPathname: triggers, nextPathname: template }, false],
            // Only guard while actually inside this scanner's editor.
            ['not currently in the editor', { ...base, currentPathname: detail, nextPathname: '/insights' }, false],
            // Genuinely leaving the editor with unsaved edits.
            ['out to the detail page', { ...base, nextPathname: detail }, true],
            ['out to an unrelated scene', { ...base, nextPathname: '/insights' }, true],
            ['closing the tab (no next location)', { ...base, nextPathname: undefined }, true],
            [
                'over to a different scanner’s editor',
                { ...base, nextPathname: urls.replayVisionScannerConfigure('other-id') },
                true,
            ],
            ['out from the self-driving step', { ...base, currentPathname: selfDriving, nextPathname: detail }, true],
            // The router stores pathnames with the `/project/:id` prefix; `urls.*` are unprefixed.
            [
                'out to settings from a project-prefixed URL',
                { ...base, currentPathname: `/project/123${triggers}`, nextPathname: '/settings/environment' },
                true,
            ],
            [
                'between steps with project-prefixed URLs',
                { ...base, currentPathname: `/project/123${configure}`, nextPathname: `/project/123${triggers}` },
                false,
            ],
        ])('%s', (_label, params, expected) => {
            expect(shouldGuardScannerNavigation(params)).toBe(expected)
        })
    })

    describe('triggerOnDemandObservation', () => {
        it.each([
            { name: 'empty string', input: '' },
            { name: 'whitespace only', input: '   ' },
        ])('bails on $name session ID without calling the API', async ({ input }) => {
            const persisted = replayScannerLogic({ id: 'abc-123' })
            persisted.mount()
            try {
                await expectLogic(persisted, () =>
                    persisted.actions.triggerOnDemandObservation(input)
                ).toDispatchActions(['triggerOnDemandObservationFailure'])
                expect(persisted.values.triggeringOnDemandObservation).toBe(false)
                expect(observeSpy).not.toHaveBeenCalled()
            } finally {
                persisted.unmount()
            }
        })

        it('bails when scanner ID is new (unsaved scanner)', async () => {
            await expectLogic(logic, () => logic.actions.triggerOnDemandObservation('019a3f47-8c2d')).toDispatchActions(
                ['triggerOnDemandObservationFailure']
            )
            expect(logic.values.triggeringOnDemandObservation).toBe(false)
            expect(observeSpy).not.toHaveBeenCalled()
        })
    })

    describe('retrying failed observations', () => {
        it('retryObservation hits the endpoint and re-arms the poll window for the replacement row', async () => {
            const persisted = replayScannerLogic({ id: 'abc-123' })
            persisted.mount()
            try {
                await expectLogic(persisted, () => persisted.actions.retryObservation('obs-1')).toDispatchActions([
                    'retryObservationSuccess',
                ])
                expect(retrySpy).toHaveBeenCalledTimes(1)
                expect(persisted.values.retryingObservationIds).toEqual([])
                // Without the grace window the replacement row, inserted moments later, is never polled in.
                expect(persisted.values.pollUntil).toBeGreaterThan(Date.now())
            } finally {
                persisted.unmount()
            }
        })
    })

    describe('background polling', () => {
        it('background reloads stay silent so the table stays interactable, foreground loads do not', () => {
            const persisted = replayScannerLogic({ id: 'abc-123' })
            persisted.mount()
            try {
                // The initial foreground load (also manual refresh, filter/sort/pagination) shows the overlay.
                expect(persisted.values.observationsLoading).toBe(true)

                persisted.actions.loadObservationsSuccess([], 0)
                expect(persisted.values.observationsLoading).toBe(false)

                // The 3s in-flight poll reloads in the background — no overlay, so rows update in place.
                persisted.actions.loadObservations(true)
                expect(persisted.values.observationsLoading).toBe(false)

                // A foreground reload still shows it — proving the silent case isn't just a no-op action.
                persisted.actions.loadObservations()
                expect(persisted.values.observationsLoading).toBe(true)
            } finally {
                persisted.unmount()
            }
        })
    })

    describe('observations drill-down round-trip', () => {
        // Guards the URL contract between the Overview chart drill-down and this logic's urlToAction:
        // a param rename on either side breaks the drill-down silently.
        it('restores the drill-down search params into the observations table filters', async () => {
            const sidLogic = replayScannerLogic({ id: 'sid' })
            sidLogic.mount()
            try {
                const params = observationsDrilldownSearchParams({
                    day: '2026-05-04',
                    interval: 'day',
                    scannerType: 'monitor',
                })
                router.actions.push(urls.replayVision('sid'), params!)
                await expectLogic(sidLogic).toFinishAllListeners()
                expect(sidLogic.values.observationDateFrom).toBe('2026-05-04')
                expect(sidLogic.values.observationDateTo).toBe('2026-05-04')
                expect(sidLogic.values.observationVerdictFilter).toEqual(['yes'])
            } finally {
                sidLogic.unmount()
            }
        })
    })

    describe('creation path telemetry', () => {
        // Both paths end on the same created event, so these captures are the only path marker.
        it.each([
            ['dead_end', 'template'],
            [null, 'scratch'],
        ])('startFromTemplate(%s) reports the %s path', (templateKey, creationMethod) => {
            const captureSpy = jest.spyOn(posthog, 'capture')
            logic.actions.startFromTemplate(templateKey)
            expect(captureSpy).toHaveBeenCalledWith('replay_vision_scanner_creation_started', {
                creation_method: creationMethod,
                template_key: templateKey,
            })
        })

        it('drafting from a goal reports the AI path without the goal text', async () => {
            const captureSpy = jest.spyOn(posthog, 'capture')
            await expectLogic(logic, () => {
                logic.actions.draftScannerFromGoal('  find users who get stuck  ')
            }).toFinishAllListeners()
            expect(captureSpy).toHaveBeenCalledWith('replay_vision_scanner_creation_started', {
                creation_method: 'ai',
                template_key: null,
                goal_length: 'find users who get stuck'.length,
            })
        })

        it.each([
            ['dead_end', 'template'],
            [null, 'scratch'],
        ])('saving after startFromTemplate(%s) completes the funnel as %s', (templateKey, creationMethod) => {
            logic.actions.startFromTemplate(templateKey)
            const captureSpy = jest.spyOn(posthog, 'capture')
            logic.actions.scannerSaved(logic.values.scanner!)
            expect(captureSpy).toHaveBeenCalledWith('replay_vision_scanner_created', {
                creation_method: creationMethod,
                scanner_type: logic.values.scanner!.scanner_type,
            })
        })

        it('records the method as unknown when the draft was resumed without a start action', () => {
            // A reload drops the in-memory creationMethod, so a save from the restored form must
            // still complete the funnel rather than throwing or reporting a wrong path.
            const captureSpy = jest.spyOn(posthog, 'capture')
            logic.actions.scannerSaved(logic.values.scanner!)
            expect(captureSpy).toHaveBeenCalledWith(
                'replay_vision_scanner_created',
                expect.objectContaining({ creation_method: 'unknown' })
            )
        })
    })

    describe('rebuildExperimentContext', () => {
        it('installs the targeting card from the form targeting', async () => {
            useMocks({
                get: {
                    '/api/projects/:team/experiments/:id/': () => [200, { id: 7, name: 'Checkout redesign' }],
                },
            })
            logic.actions.setScannerValues({ experiment_targeting: { experiment_id: 7, variant: 'control' } })

            await expectLogic(logic, () => logic.actions.rebuildExperimentContext()).toFinishAllListeners()

            expect(logic.values.experimentContext).toEqual({
                experiment: { id: 7, name: 'Checkout redesign' },
                variantKey: 'control',
            })
        })

        it('does not restore targeting a template pick discarded while the request was in flight', async () => {
            useMocks({
                get: {
                    '/api/projects/:team/experiments/:id/': () => [200, { id: 7, name: 'Checkout redesign' }],
                },
            })
            logic.actions.setScannerValues({ experiment_targeting: { experiment_id: 7, variant: 'control' } })

            await expectLogic(logic, () => {
                logic.actions.rebuildExperimentContext()
                // Fires during the in-flight experiment request; resetScanner drops the form targeting.
                logic.actions.startFromTemplate(null)
            }).toFinishAllListeners()

            expect(logic.values.scanner?.experiment_targeting).toBeFalsy()
            expect(logic.values.experimentContext).toBeNull()
        })
    })
})
