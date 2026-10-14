import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import { llmSkillsList } from 'products/skills/frontend/generated/api'

import { llmSkillsLogic } from './llmSkillsLogic'

jest.mock('products/skills/frontend/generated/api', () => ({
    llmSkillsList: jest.fn(),
}))

const mockList = llmSkillsList as jest.MockedFunction<typeof llmSkillsList>

describe('llmSkillsLogic', () => {
    let logic: ReturnType<typeof llmSkillsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    afterEach(() => {
        logic?.unmount()
    })

    it.each([
        ['flat list', false],
        ['grouped list', true],
    ])('renders an empty %s when the list response has no body', async (_desc, groupByPrefix) => {
        // The API layer resolves a 204 or an empty body to null, although the generated type says otherwise.
        mockList.mockResolvedValue(null as unknown as Awaited<ReturnType<typeof llmSkillsList>>)
        logic = llmSkillsLogic()
        logic.mount()
        logic.actions.setFilters({ group_by_prefix: groupByPrefix }, true, false)
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.skills).toEqual({ results: [], count: 0 })
        expect(logic.values.count).toBe(0)
        expect(logic.values.skillCountLabel).toBe('0 skills')
        expect(logic.values.groupedSkills === null).toBe(!groupByPrefix)
    })
})
