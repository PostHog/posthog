import { waitFor } from '@testing-library/react'
/* oxlint-disable react-hooks/rules-of-hooks -- useMocks is a test helper, not a React hook */
import { expectLogic } from 'kea-test-utils'

import { resumeKeaLoadersErrors, silenceKeaLoadersErrors } from '~/initKea'
import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import type { ScoutRubricCriterionApi, ScoutRubricDocumentApi } from 'products/signals/frontend/generated/api.schemas'

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
        ...overrides,
    }
}

function makeGeneration(
    status: 'queued' | 'running' | 'completed' | 'failed'
): NonNullable<ScoutRubricDocumentApi['generation']> {
    return {
        id: 'example-generation',
        status,
        requested_at: '2026-09-01T10:00:00Z',
        completed_at: status === 'completed' ? '2026-09-01T10:01:00Z' : null,
        task_id: 'example-task',
        task_run_id: 'example-task-run',
        error: status === 'failed' ? 'Generation failed. Try again.' : null,
        suggestions: status === 'completed' ? [suggestion] : [],
        summary: '',
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
        document = makeDocument({ generation: makeGeneration('running') })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.generationActive).toBe(true)

        logic.actions.updateCriterion(criterion.id, { title: 'My edited criterion' })
        document = makeDocument({ revision: 1, generation: makeGeneration('completed') })
        await expectLogic(logic, () => logic.actions.loadRubrics()).toFinishAllListeners()

        expect(logic.values.draftCriteria[0].title).toBe('My edited criterion')
        expect(logic.values.draftRevision).toBe(0)
        expect(logic.values.generationActive).toBe(false)
        expect(logic.values.availableSuggestions).toEqual([suggestion])
        expect(logic.values.hasUnsavedChanges).toBe(true)
    })

    it.each([false, true])('saves selected suggestions with an optional add step (%s)', async (addBeforeSaving) => {
        const unselectedSuggestion = { ...suggestion, id: 'custom-other' }
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
                        criteria: [{ ...criterion, enabled: false }, suggestion],
                    })
                    return [200, document]
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.hasUnsavedChanges).toBe(false)
        expect(logic.values.newCriteriaCount).toBe(0)
        logic.actions.toggleSuggestion(suggestion.id, true)
        expect(logic.values.hasUnsavedChanges).toBe(true)
        expect(logic.values.newCriteriaCount).toBe(1)
        logic.actions.toggleSuggestion(suggestion.id, false)
        expect(logic.values.hasUnsavedChanges).toBe(false)
        expect(logic.values.newCriteriaCount).toBe(0)
        logic.actions.updateCriterion(criterion.id, { enabled: false })
        expect(logic.values.newCriteriaCount).toBe(0)
        logic.actions.toggleSuggestion(suggestion.id, true)
        if (addBeforeSaving) {
            logic.actions.addSelectedSuggestions()
            logic.actions.addSelectedSuggestions()
            expect(logic.values.newCriteriaCount).toBe(1)
            logic.actions.removeCriterion(suggestion.id)
            expect(logic.values.newCriteriaCount).toBe(0)
            logic.actions.toggleSuggestion(suggestion.id, true)
            logic.actions.addSelectedSuggestions()
        }
        expect(logic.values.newCriteriaCount).toBe(1)
        logic.actions.addCriterion()
        expect(logic.values.newCriteriaCount).toBe(2)
        logic.actions.removeCriterion(logic.values.draftCriteria[logic.values.draftCriteria.length - 1].id)
        expect(logic.values.newCriteriaCount).toBe(1)
        await expectLogic(logic, () => logic.actions.generateSuggestions()).toFinishAllListeners()
        expect(starts).toBe(0)

        await expectLogic(logic, () => logic.actions.saveRubrics()).toFinishAllListeners()

        expect(submitted).toEqual({ revision: 3, criteria: [{ ...criterion, enabled: false }, suggestion] })
        expect(logic.values.draftRevision).toBe(4)
        expect(logic.values.hasUnsavedChanges).toBe(false)
        expect(logic.values.newCriteriaCount).toBe(0)
        expect(logic.values.selectedSuggestionIds).toEqual([])
        expect(logic.values.availableSuggestions).toEqual([unselectedSuggestion])
        expect(logic.values.sortedCriteria).toEqual([suggestion, { ...criterion, enabled: false }])

        await expectLogic(logic, () => logic.actions.loadRubrics({ resetDraft: true })).toFinishAllListeners()
        expect(logic.values.draftCriteria).toEqual([{ ...criterion, enabled: false }, suggestion])
        expect(logic.values.availableSuggestions).toEqual([unselectedSuggestion])

        await expectLogic(logic, () => logic.actions.generateSuggestions()).toFinishAllListeners()
        expect(starts).toBe(1)
        expect(logic.values.generationActive).toBe(true)
    })

    it.each([409, 503])('preserves edits after a %s save failure and recovers explicitly', async (status) => {
        document = makeDocument({ generation: makeGeneration('completed') })
        useMocks({ put: { [RUBRICS_URL]: () => [status, { detail: 'Could not save rubrics.' }] } })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        logic.actions.updateCriterion(criterion.id, { title: 'Keep this edit' })
        logic.actions.toggleSuggestion(suggestion.id, true)

        await expectLogic(logic, () => logic.actions.saveRubrics()).toFinishAllListeners()
        expect(logic.values.draftCriteria[0].title).toBe('Keep this edit')
        expect(logic.values.selectedSuggestions).toEqual([suggestion])
        expect(logic.values.newCriteriaCount).toBe(1)
        expect(logic.values.saving).toBe(false)
        expect(logic.values.saveConflict).toBe(status === 409)

        document = makeDocument({ revision: 2 })
        await expectLogic(logic, () => logic.actions.loadRubrics({ resetDraft: true })).toFinishAllListeners()
        expect(logic.values.draftRevision).toBe(2)
        expect(logic.values.saveConflict).toBe(false)
        expect(logic.values.saveError).toBe(null)
    })

    it('starts only one generation while the request is pending and allows retry after a failure', async () => {
        let release: (() => void) | undefined
        const pending = new Promise<void>((resolve) => {
            release = resolve
        })
        let starts = 0
        useMocks({
            post: {
                [GENERATE_URL]: async () => {
                    starts += 1
                    await pending
                    return [503, { detail: 'Generation is unavailable. Try again.' }]
                },
            },
        })
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()

        logic.actions.generateSuggestions()
        logic.actions.generateSuggestions()
        await waitFor(() => expect(starts).toBe(1))
        expect(logic.values.generationSubmitting).toBe(true)
        release?.()
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.generationSubmitting).toBe(false)
        expect(logic.values.generationError).toBe('Generation is unavailable. Try again.')

        useMocks({ post: { [GENERATE_URL]: () => [202, makeDocument({ generation: makeGeneration('queued') })] } })
        await expectLogic(logic, () => logic.actions.generateSuggestions()).toFinishAllListeners()
        expect(logic.values.generationActive).toBe(true)
        expect(logic.values.generationError).toBe(null)
    })

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

    it.each(['an incomplete manual criterion', 'too many selected criteria'])(
        'blocks saving %s',
        async (invalidInput) => {
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
                expect(logic.values.expandedCriterionId).toBe(logic.values.draftCriteria[1].id)
            } else {
                logic.actions.toggleSuggestion(suggestion.id, true)
            }
            await expectLogic(logic, () => logic.actions.saveRubrics()).toFinishAllListeners()
            expect(saves).toBe(0)
            expect(logic.values.validationError).not.toBe(null)
        }
    )
})
