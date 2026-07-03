import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { urls } from 'scenes/urls'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { parseCsvParam, parseSortParam } from '../utils/urlParams'
import {
    buildObservationListParams,
    ObservationStatusValue,
    ObservationTriggeredByValue,
    ObservationVerdictValue,
    replayScannerLogic,
    shouldGuardScannerNavigation,
} from './replayScannerLogic'
import { defaultScannerTemplates } from './scannerTemplates'
import { ClassifierScanner, ReplayScanner, ScorerScanner } from './types'

describe('replayScannerLogic', () => {
    let logic: ReturnType<typeof replayScannerLogic.build>
    let observeSpy: jest.Mock
    let retrySpy: jest.Mock
    let suggestSpy: jest.Mock
    let createSpy: jest.Mock

    beforeEach(() => {
        observeSpy = jest.fn(() => [202, { workflow_id: 'wf-test' }])
        retrySpy = jest.fn(() => [202, { workflow_id: 'wf-retry' }])
        suggestSpy = jest.fn(() => [200, { suggestions: [] }])
        createSpy = jest.fn(() => [201, { id: 'created-scanner' }])
        useMocks({
            get: {
                '/api/projects/:team/vision/scanners/:id/': () => [404, {}],
                '/api/projects/:team/vision/scanners/:id/observations/': { results: [] },
            },
            post: {
                '/api/projects/:team/vision/scanners/': createSpy,
                '/api/projects/:team/vision/scanners/:id/observe/': observeSpy,
                '/api/projects/:team/vision/scanners/:id/observations/:obsId/retry/': retrySpy,
                '/api/projects/:team/vision/scanners/suggest_tags/': suggestSpy,
            },
        })
        initKeaTests()
        logic = replayScannerLogic({ id: 'new' })
        logic.mount()
    })

    afterEach(() => {
        logic?.unmount()
    })

    describe('form defaults', () => {
        it('new scanner starts as monitor with empty prompt and default sampling', () => {
            expect(logic.values.scanner).toMatchObject({
                id: 'new',
                name: '',
                enabled: true,
                scanner_type: 'monitor',
                scanner_config: { prompt: '' },
                sampling_rate: 1,
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
            logic.actions.setSubmitIntent('advance')
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            expect(router.values.location.pathname).toContain('/replay-vision/new/triggers')
            expect(logic.values.submitIntent).toBe('save')
        })

        it('advance does not mark the draft as saved, so the unsaved-changes guard stays armed', async () => {
            router.actions.push('/replay-vision/new/configure')
            logic.actions.setScannerValues({ name: 'Draft scanner', scanner_config: { prompt: 'Q?' } })
            logic.actions.setSubmitIntent('advance')
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            // The draft must not be adopted as the saved baseline — no API write happened.
            expect(logic.values.originalScanner?.name).toBe('')
            expect(logic.values.hasUnsavedChanges).toBe(true)
        })

        it('default-intent submit (Enter) on the new-scanner configure step advances instead of creating', async () => {
            router.actions.push('/replay-vision/new/configure')
            logic.actions.setScannerValues({ name: 'Test scanner', scanner_config: { prompt: 'Q?' } })
            await expectLogic(logic, () => logic.actions.submitScanner()).toFinishAllListeners()
            expect(createSpy).not.toHaveBeenCalled()
            expect(router.values.location.pathname).toContain('/replay-vision/new/triggers')
        })
    })

    describe('validation errors', () => {
        it.each([
            {
                name: 'flags missing name',
                setup: () => undefined,
                expectedErrors: { name: 'Name is required' },
            },
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
                    scanner_config: expect.objectContaining({ tags: expect.stringContaining('at least one tag') }),
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
                    scanner_config: expect.objectContaining({ tags: 'Tags must be unique' }),
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
                    scanner_config: expect.objectContaining({ tags: "Tags can't be blank" }),
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
            observationSubjectFilter: '',
            observationsSort: null,
            scanner: null,
        }

        it('returns empty params when no filters, sort, or pagination', () => {
            expect(buildObservationListParams({ ...emptyValues })).toEqual({})
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

    describe('shouldGuardScannerNavigation', () => {
        const scannerId = 'abc-123'
        const configure = urls.replayVisionScannerConfigure(scannerId)
        const triggers = urls.replayVisionScannerTriggers(scannerId)
        const template = urls.replayVisionScannerTemplate(scannerId)
        const detail = urls.replayVision(scannerId)
        const base = { hasUnsavedChanges: true, isSubmitting: false, scannerId, currentPathname: configure }

        it.each([
            // Nothing to lose, or the editor is mid-submit (save / step advance redirects itself).
            ['no unsaved changes', { ...base, hasUnsavedChanges: false, nextPathname: '/insights' }, false],
            ['mid-submit redirect to detail', { ...base, isSubmitting: true, nextPathname: detail }, false],
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

        it('bails on unsaved scanners without calling the API', async () => {
            await expectLogic(logic, () => logic.actions.retryObservation('obs-1')).toDispatchActions([
                'retryObservationFailure',
            ])
            expect(retrySpy).not.toHaveBeenCalled()
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
})
