import { expectLogic } from 'kea-test-utils'

import { productSetupStatusLogic } from 'lib/components/ProductEmptyState/productSetupStatusLogic'

import { ProductKey } from '~/queries/schema/schema-general'
import { initKeaTests } from '~/test/init'

import { llmSkillsList } from 'products/skills/frontend/generated/api'

import { llmSkillsSetupLogic } from './llmSkillsSetupLogic'

jest.mock('products/skills/frontend/generated/api', () => ({
    llmSkillsList: jest.fn(),
}))

const mockLlmSkillsList = llmSkillsList as jest.MockedFunction<typeof llmSkillsList>

// Guards the connect + mapping into the app-wide setup-status layer: if either
// breaks, the scene empty-state gate strands on its spinner or shows the wrong surface.
describe('llmSkillsSetupLogic', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
    })

    it.each([
        [0, 'needs-setup'],
        [1, 'has-data'],
        [42, 'has-data'],
    ])('pushes a skill count of %i as status %s', async (count, expected) => {
        mockLlmSkillsList.mockResolvedValue({ count, next: null, previous: null, results: [] })
        const logic = llmSkillsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.SKILLS }).values.status).toBe(expected)
    })

    it('fails open to unknown when the count query fails before any answer', async () => {
        mockLlmSkillsList.mockRejectedValue(new Error('network down'))
        const logic = llmSkillsSetupLogic()
        logic.mount()
        await expectLogic(logic).toFinishAllListeners()
        expect(productSetupStatusLogic({ productKey: ProductKey.SKILLS }).values.status).toBe('unknown')
    })
})
