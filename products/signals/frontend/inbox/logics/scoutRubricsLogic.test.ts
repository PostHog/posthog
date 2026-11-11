import { waitFor } from '@testing-library/react'
/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

// Imported from the source module rather than the `@posthog/lemon-ui` barrel, so the spy below
// replaces the method on the same `lemonToast` singleton the logic calls at runtime.
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type {
    ScoutRubricCriterionApi,
    ScoutRubricDocumentApi,
    ScoutRubricSaveApi,
} from 'products/signals/frontend/generated/api.schemas'

import { scoutRubricReferenceFixture } from '../components/config/scouts/scoutRubricFixtures'
import { MAX_SCOUT_RUBRICS, scoutRubricsLogic } from './scoutRubricsLogic'

const RUBRICS_URL = '/api/projects/:team_id/signals/scout/rubrics/:config_id/'
const GENERATE_URL = `${RUBRICS_URL}generate/`
const criterion: ScoutRubricCriterionApi = {
    id: 'default-evidence',
    title: 'Evidence supports the finding',
    description: 'Check that the finding is supported by inspected evidence.',
    pass_condition: 'The cited evidence supports the claim without unsupported conclusions.',
    applicability: 'Runs that produce findings.',
    enabled: true,
    source: 'default',
}
const suggestion: ScoutRubricCriterionApi = {
    ...criterion,
    id: 'custom-window',
    title: 'Use the requested time window',
    description: 'Check that the investigation covers the requested period.',
    pass_condition: 'Queries use the time window stated in the scout instructions.',
    applicability: 'Runs that query recent activity.',
    source: 'custom',
}

function makeDocument(overrides: Partial<ScoutRubricDocumentApi> = {}): ScoutRubricDocumentApi {
    return {
        config_id: 'example-scout-config',
        skill_name: 'signals-scout-example',
        revision: 0,
        criteria: [criterion],
        generation: null,
        reference_context: null,
        reference_generation_id: null,
        ...overrides,
    }
}

function makeGeneration(
    status: 'queued' | 'running' | 'completed' | 'failed'
): NonNullable<ScoutRubricDocumentApi['generation']> {
    return {
        id: 'example-generation',
        status,
        context: '',
        requested_at: '2026-09-01T10:00:00Z',
        completed_at: status === 'completed' ? '2026-09-01T10:01:00Z' : null,
        task_id: 'example-task',
        task_run_id: 'example-task-run',
        error: status === 'failed' ? 'Generation failed. Try again.' : null,
        suggestions: status === 'completed' ? [suggestion] : [],
        summary: '',
        reference_context: status === 'completed' ? scoutRubricReferenceFixture : null,
    }
}

describe('scoutRubricsLogic', () => {
    let logic: ReturnType<typeof scoutRubricsLogic.build>
    let document: ScoutRubricDocumentApi

    beforeEach(() => {
        initKeaTests()
        silenceKeaLoadersErrors()
        document = makeDocument()
        useMocks({ get: { [RUBRICS_URL]: () => [200, document] } })
        logic = scoutRubricsLogic({ teamId: 2, configId: document.config_id })
    })

    afterEach(() => {
        logic.unmount()
        resumeKeaLoadersErrors()
    })

    it('restores a background generation after reopening without replacing edits when results arrive', async () => {
        document = makeDocument({
            generation: { ...makeGeneration('running'), context: 'Focus from an earlier request.' },
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.generationActive).toBe(true)
        expect(logic.values.generationContext).toBe('')

        logic.actions.updateCriterion(criterion.id, { title: 'My edited criterion' })
        document = makeDocument({ revision: 1, generation: makeGeneration('completed') })
        await expectLogic(logic, () => logic.actions.loadRubrics()).toFinishAllListeners()

        expect(logic.values.draftCriteria[0].title).toBe('My edited criterion')
        expect(logic.values.draftRevision).toBe(0)
        expect(logic.values.generationActive).toBe(false)
        expect(logic.values.availableSuggestions).toEqual([suggestion])
        expect(logic.values.hasUnsavedChanges).toBe(true)
    })

    it('shows elapsed time from the saved request while generation is active', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        jest.useFakeTimers()
        try {
            jest.setSystemTime(new Date('2026-09-01T10:01:24Z'))
            logic.actions.loadRubricsSuccess(makeDocument({ generation: makeGeneration('running') }))
            expect(logic.values.generationElapsedLabel).toBe('1:24')

            jest.advanceTimersByTime(1000)
            expect(logic.values.generationElapsedLabel).toBe('1:25')

            logic.actions.loadRubricsSuccess(makeDocument({ generation: makeGeneration('completed') }))
            expect(logic.values.generationElapsedLabel).toBe(null)
        } finally {
            logic.actions.loadRubricsSuccess(makeDocument())
            jest.useRealTimers()
        }
    })

    it('keeps suggestion edits inline through polling and saves only selected suggestions', async () => {
        const unselectedSuggestion = { ...suggestion, id: 'custom-other' }
        const editedSuggestion = { ...suggestion, title: 'Check the complete requested period' }
        const editedUnselectedSuggestion = { ...unselectedSuggestion, title: 'Keep this for later' }
        const generation = { ...makeGeneration('completed'), suggestions: [suggestion, unselectedSuggestion] }
        document = makeDocument({ revision: 3, generation })
        let submitted: unknown
        let starts = 0
        useMocks({
            post: {
                [GENERATE_URL]: () => {
                    starts += 1
                    return [202, { ...document, generation: makeGeneration('queued') }]
                },
            },
            put: {
                [RUBRICS_URL]: async ({ request }) => {
                    submitted = await request.json()
                    document = makeDocument({
                        revision: 4,
                        generation,
                        criteria: [{ ...criterion, enabled: false }, editedSuggestion],
                        reference_context: scoutRubricReferenceFixture,
                        reference_generation_id: makeGeneration('completed').id,
                    })
                    return [200, document]
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.hasUnsavedChanges).toBe(false)
        expect(logic.values.newCriteriaCount).toBe(0)
        expect(logic.values.allSuggestionsSelected).toBe(false)
        logic.actions.toggleAllSuggestions(true)
        expect(logic.values.allSuggestionsSelected).toBe(true)
        expect(logic.values.newCriteriaCount).toBe(2)
        logic.actions.toggleAllSuggestions(false)
        expect(logic.values.allSuggestionsSelected).toBe(false)
        expect(logic.values.hasUnsavedChanges).toBe(false)
        logic.actions.toggleSuggestion(suggestion.id, true)
        expect(logic.values.hasUnsavedChanges).toBe(true)
        expect(logic.values.newCriteriaCount).toBe(1)
        logic.actions.toggleSuggestion(suggestion.id, false)
        expect(logic.values.hasUnsavedChanges).toBe(false)
        expect(logic.values.newCriteriaCount).toBe(0)
        logic.actions.updateCriterion(criterion.id, { enabled: false })
        expect(logic.values.newCriteriaCount).toBe(0)
        logic.actions.updateSuggestion(suggestion.id, { title: editedSuggestion.title })
        expect(logic.values.selectedSuggestionIds).toEqual([suggestion.id])
        logic.actions.updateSuggestion(unselectedSuggestion.id, { title: editedUnselectedSuggestion.title })
        logic.actions.toggleSuggestion(unselectedSuggestion.id, false)
        await expectLogic(logic, () => logic.actions.loadRubrics()).toFinishAllListeners()
        expect(logic.values.availableSuggestions).toEqual([editedSuggestion, editedUnselectedSuggestion])
        expect(logic.values.draftCriteria).toEqual([{ ...criterion, enabled: false }])
        expect(logic.values.newCriteriaCount).toBe(1)
        logic.actions.addCriterion()
        expect(logic.values.newCriteriaCount).toBe(2)
        expect(logic.values.expandedCriterionId).toBe(logic.values.draftCriteria[1].id)
        logic.actions.removeCriterion(logic.values.draftCriteria[logic.values.draftCriteria.length - 1].id)
        expect(logic.values.newCriteriaCount).toBe(1)
        await expectLogic(logic, () => logic.actions.generateSuggestions()).toFinishAllListeners()
        expect(starts).toBe(0)

        await expectLogic(logic, () => logic.actions.saveRubrics()).toFinishAllListeners()

        expect(submitted).toEqual({
            revision: 3,
            criteria: [{ ...criterion, enabled: false }, editedSuggestion],
            adopt_generation_id: makeGeneration('completed').id,
        })
        expect(logic.values.draftRevision).toBe(4)
        expect(logic.values.hasUnsavedChanges).toBe(false)
        expect(logic.values.draftAdoptGenerationId).toBeNull()
        expect(logic.values.newCriteriaCount).toBe(0)
        expect(logic.values.selectedSuggestionIds).toEqual([])
        expect(logic.values.availableSuggestions).toEqual([editedUnselectedSuggestion])
        expect(logic.values.customCriteria).toEqual([editedSuggestion])
        expect(logic.values.sharedCriteria).toEqual([{ ...criterion, enabled: false }])

        await expectLogic(logic, () => logic.actions.loadRubrics({ resetDraft: true })).toFinishAllListeners()
        expect(logic.values.draftCriteria).toEqual([{ ...criterion, enabled: false }, editedSuggestion])
        expect(logic.values.availableSuggestions).toEqual([editedUnselectedSuggestion])

        await expectLogic(logic, () => logic.actions.generateSuggestions()).toFinishAllListeners()
        expect(starts).toBe(1)
        expect(logic.values.generationActive).toBe(true)

        document = { ...document, generation: { ...generation, id: 'next-generation' } }
        await expectLogic(logic, () => logic.actions.loadRubrics()).toFinishAllListeners()
        expect(logic.values.availableSuggestions).toEqual([unselectedSuggestion])
        expect(logic.values.selectedSuggestionIds).toEqual([])
    })

    it.each([false, true])(
        'adopts a captured reference only when selected, without adding criteria (saved reference: %s)',
        async (hasSavedReference) => {
            const generation = { ...makeGeneration('completed'), suggestions: [] }
            document = makeDocument({
                revision: 2,
                generation,
                reference_context: hasSavedReference ? { ...scoutRubricReferenceFixture, skill_version: 2 } : null,
                reference_generation_id: hasSavedReference ? 'previous-generation' : null,
            })
            const submissions: unknown[] = []
            useMocks({
                put: {
                    [RUBRICS_URL]: async ({ request }) => {
                        const data = (await request.json()) as ScoutRubricSaveApi
                        submissions.push(data)
                        document = { ...document, criteria: data.criteria, revision: document.revision + 1 }
                        return [200, document]
                    },
                },
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.hasUnsavedChanges).toBe(false)

            logic.actions.updateCriterion(criterion.id, { title: 'Reviewed evidence criterion' })
            await expectLogic(logic, () => logic.actions.saveRubrics()).toFinishAllListeners()
            expect(submissions[0]).toEqual({
                revision: 2,
                criteria: [{ ...criterion, title: 'Reviewed evidence criterion' }],
            })

            logic.actions.adoptGenerationReference()
            expect(logic.values.hasUnsavedChanges).toBe(true)
            await expectLogic(logic, () => logic.actions.saveRubrics()).toFinishAllListeners()
            expect(submissions[1]).toEqual({
                revision: 3,
                criteria: [{ ...criterion, title: 'Reviewed evidence criterion' }],
                adopt_generation_id: generation.id,
            })
        }
    )

    it.each([409, 503])('preserves edits after a %s save failure and recovers explicitly', async (status) => {
        document = makeDocument({ generation: makeGeneration('completed') })
        useMocks({ put: { [RUBRICS_URL]: () => [status, { detail: 'Could not save rubrics.' }] } })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.updateCriterion(criterion.id, { title: 'Keep this edit' })
        logic.actions.updateSuggestion(suggestion.id, { title: 'Keep this suggestion edit' })

        await expectLogic(logic, () => logic.actions.saveRubrics()).toFinishAllListeners()
        expect(logic.values.draftCriteria[0].title).toBe('Keep this edit')
        expect(logic.values.selectedSuggestions).toEqual([{ ...suggestion, title: 'Keep this suggestion edit' }])
        expect(logic.values.newCriteriaCount).toBe(1)
        expect(logic.values.saving).toBe(false)
        expect(logic.values.saveConflict).toBe(status === 409)

        document = makeDocument({ revision: 2 })
        await expectLogic(logic, () => logic.actions.loadRubrics({ resetDraft: true })).toFinishAllListeners()
        expect(logic.values.draftRevision).toBe(2)
        expect(logic.values.saveConflict).toBe(false)
        expect(logic.values.saveError).toBe(null)
    })

    it.each(['', '  Check repeat findings carefully.  '])(
        'keeps optional focus until a generation that received it starts (%s)',
        async (context) => {
            let release: (() => void) | undefined
            const pending = new Promise<void>((resolve) => {
                release = resolve
            })
            let starts = 0
            let submitted: unknown
            useMocks({
                post: {
                    [GENERATE_URL]: async ({ request }) => {
                        starts += 1
                        submitted = await request.json()
                        await pending
                        return [503, { detail: 'Generation is unavailable. Try again.' }]
                    },
                },
            })
            logic.mount()
            await expectLogic(logic).toFinishAllListeners()

            logic.actions.setGenerationContext(context)
            expect(logic.values.hasUnsavedChanges).toBe(false)
            logic.actions.generateSuggestions()
            logic.actions.generateSuggestions()
            await waitFor(() => expect(starts).toBe(1))
            expect(logic.values.generationSubmitting).toBe(true)
            expect(submitted).toEqual({ context: context.trim() })
            release?.()
            await expectLogic(logic).toFinishAllListeners()
            expect(logic.values.generationSubmitting).toBe(false)
            expect(logic.values.generationError).toBe('Generation is unavailable. Try again.')
            expect(logic.values.generationContext).toBe(context)

            const toast = jest.spyOn(lemonToast, 'info').mockReturnValue('toast-1')
            const otherSessionGeneration = { ...makeGeneration('queued'), context: 'Focus from another session.' }
            useMocks({ post: { [GENERATE_URL]: () => [202, makeDocument({ generation: otherSessionGeneration })] } })
            await expectLogic(logic, () => logic.actions.generateSuggestions()).toFinishAllListeners()
            expect(logic.values.generationActive).toBe(true)
            expect(logic.values.generationContext).toBe(context)
            expect(toast).toHaveBeenCalledTimes(context.trim() ? 1 : 0)

            document = makeDocument({ generation: { ...otherSessionGeneration, status: 'failed' } })
            await expectLogic(logic, () => logic.actions.loadRubrics()).toFinishAllListeners()
            useMocks({
                post: {
                    [GENERATE_URL]: async ({ request }) => {
                        const { context: received } = (await request.json()) as { context: string }
                        return [202, makeDocument({ generation: { ...makeGeneration('queued'), context: received } })]
                    },
                },
            })
            await expectLogic(logic, () => logic.actions.generateSuggestions()).toFinishAllListeners()
            expect(logic.values.generationActive).toBe(true)
            expect(logic.values.generationError).toBe(null)
            expect(logic.values.generationContext).toBe('')
        }
    )

    it('does not let an older read replace a generation that has just started', async () => {
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        let release: (() => void) | undefined
        const pending = new Promise<void>((resolve) => {
            release = resolve
        })
        let readStarted = false
        useMocks({
            get: {
                [RUBRICS_URL]: async () => {
                    readStarted = true
                    await pending
                    return [200, document]
                },
            },
            post: { [GENERATE_URL]: () => [202, makeDocument({ generation: makeGeneration('queued') })] },
        })
        logic.actions.loadRubrics()
        await waitFor(() => expect(readStarted).toBe(true))
        logic.actions.generateSuggestions()
        await waitFor(() => expect(logic.values.generationActive).toBe(true))
        release?.()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.generationActive).toBe(true)
    })

    it.each([
        'an incomplete manual criterion',
        'an incomplete edited suggestion',
        'too many selected criteria',
        'suggestions without a captured reference',
        'edited suggestions without a captured reference',
        'all suggestions without a captured reference',
    ])('blocks saving %s', async (invalidInput) => {
        if (invalidInput === 'too many selected criteria') {
            document = makeDocument({
                criteria: Array.from(
                    { length: MAX_SCOUT_RUBRICS },
                    (_, index): ScoutRubricCriterionApi => ({
                        ...criterion,
                        id: `custom-existing-${index}`,
                        source: 'custom',
                    })
                ),
                generation: makeGeneration('completed'),
            })
        } else if (invalidInput === 'an incomplete edited suggestion') {
            document = makeDocument({ generation: makeGeneration('completed') })
        } else if (invalidInput.includes('without a captured reference')) {
            document = makeDocument({
                generation: { ...makeGeneration('completed'), reference_context: null },
                reference_context: scoutRubricReferenceFixture,
                reference_generation_id: 'previous-generation',
            })
        }
        let saves = 0
        useMocks({
            put: {
                [RUBRICS_URL]: () => {
                    saves += 1
                    return [200, document]
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        if (invalidInput === 'an incomplete manual criterion') {
            logic.actions.addCriterion()
        } else if (invalidInput === 'an incomplete edited suggestion') {
            logic.actions.updateSuggestion(suggestion.id, { pass_condition: '' })
        } else if (invalidInput === 'edited suggestions without a captured reference') {
            logic.actions.updateSuggestion(suggestion.id, { title: 'Edited suggestion' })
        } else if (invalidInput === 'all suggestions without a captured reference') {
            logic.actions.toggleAllSuggestions(true)
        } else {
            logic.actions.toggleSuggestion(suggestion.id, true)
        }
        await expectLogic(logic, () => logic.actions.saveRubrics()).toFinishAllListeners()
        expect(saves).toBe(0)
        expect(logic.values.validationError).not.toBe(null)
    })
})
