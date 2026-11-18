import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { llmSkillsList } from 'products/skills/frontend/generated/api'
import type { LLMSkillListApi } from 'products/skills/frontend/generated/api.schemas'

import { SKILL_OPTIONS_PAGE_SIZE, taskSkillsPickerLogic } from './taskSkillsPickerLogic'

jest.mock('posthog-js')
jest.mock('products/skills/frontend/generated/api')

const mockSkillsList = llmSkillsList as jest.MockedFunction<typeof llmSkillsList>

function makeSkill(name: string): LLMSkillListApi {
    return { name, description: `What ${name} covers.` } as LLMSkillListApi
}

function respondWith(names: string[], count = names.length): void {
    mockSkillsList.mockResolvedValue({ count, results: names.map(makeSkill) } as any)
}

describe('taskSkillsPickerLogic', () => {
    let logic: ReturnType<typeof taskSkillsPickerLogic.build>

    beforeEach(() => {
        initKeaTests()
        mockSkillsList.mockReset()
        respondWith(['error-triage'])
        logic = taskSkillsPickerLogic()
        logic.mount()
    })

    afterEach(() => {
        logic.unmount()
    })

    it('loads the first page once however many times focus asks for it', async () => {
        await expectLogic(logic, () => {
            logic.actions.ensureOptionsLoaded()
        }).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.ensureOptionsLoaded()
        }).toFinishAllListeners()

        expect(mockSkillsList).toHaveBeenCalledTimes(1)
    })

    it('excludes categorized skills so scouts do not fill the dropdown', async () => {
        await expectLogic(logic, () => {
            logic.actions.ensureOptionsLoaded()
        }).toFinishAllListeners()

        expect(mockSkillsList).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ category: '' }))
    })

    it('collapses a burst of keystrokes into one search request', async () => {
        await expectLogic(logic, () => {
            logic.actions.setSearch('err')
            logic.actions.setSearch('erro')
            logic.actions.setSearch('error')
        }).toFinishAllListeners()

        expect(mockSkillsList).toHaveBeenCalledTimes(1)
        expect(mockSkillsList).toHaveBeenCalledWith(expect.any(String), expect.objectContaining({ search: 'error' }))
    })

    it('does not reload when the input resets to the current search', async () => {
        await expectLogic(logic, () => {
            logic.actions.ensureOptionsLoaded()
        }).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.setSearch('')
        }).toFinishAllListeners()

        expect(mockSkillsList).toHaveBeenCalledTimes(1)
    })

    it('appends the next page from the end of what is already loaded', async () => {
        respondWith(['a', 'b'], 4)
        await expectLogic(logic, () => {
            logic.actions.ensureOptionsLoaded()
        }).toFinishAllListeners()

        respondWith(['c', 'd'], 4)
        await expectLogic(logic, () => {
            logic.actions.loadNextPage()
        }).toFinishAllListeners()

        expect(mockSkillsList).toHaveBeenLastCalledWith(expect.any(String), expect.objectContaining({ offset: 2 }))
        expect(logic.values.skillOptions.map((skill) => skill.name)).toEqual(['a', 'b', 'c', 'd'])
    })

    it('restarts paging at the top when the search changes', async () => {
        // Carrying the previous offset into a new search is the bug this pattern invites: it
        // both duplicates rows in the dropdown and hides matches behind an offset that no
        // longer means anything.
        respondWith(['a', 'b'], 4)
        await expectLogic(logic, () => {
            logic.actions.ensureOptionsLoaded()
        }).toFinishAllListeners()
        await expectLogic(logic, () => {
            logic.actions.loadNextPage()
        }).toFinishAllListeners()

        respondWith(['error-triage'], 1)
        await expectLogic(logic, () => {
            logic.actions.setSearch('error')
        }).toFinishAllListeners()

        expect(mockSkillsList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ offset: 0, search: 'error', limit: SKILL_OPTIONS_PAGE_SIZE })
        )
        expect(logic.values.skillOptions.map((skill) => skill.name)).toEqual(['error-triage'])
    })

    it('ignores load more while a replacement search is pending', async () => {
        respondWith(['a', 'b'], 4)
        await expectLogic(logic, () => {
            logic.actions.ensureOptionsLoaded()
        }).toFinishAllListeners()

        respondWith(['error-triage'], 1)
        await expectLogic(logic, () => {
            logic.actions.setSearch('error')
            logic.actions.loadNextPage()
        }).toFinishAllListeners()

        expect(mockSkillsList).toHaveBeenCalledTimes(2)
        expect(mockSkillsList).toHaveBeenLastCalledWith(
            expect.any(String),
            expect.objectContaining({ offset: 0, search: 'error' })
        )
        expect(logic.values.skillOptions.map((skill) => skill.name)).toEqual(['error-triage'])
    })

    it('knows when more skills are waiting behind the loaded page', async () => {
        respondWith(['a', 'b'], 4)
        await expectLogic(logic, () => {
            logic.actions.ensureOptionsLoaded()
        }).toFinishAllListeners()

        expect(logic.values.hasMoreSkills).toBe(true)

        respondWith(['c', 'd'], 4)
        await expectLogic(logic, () => {
            logic.actions.loadNextPage()
        }).toFinishAllListeners()

        expect(logic.values.hasMoreSkills).toBe(false)
    })
})
