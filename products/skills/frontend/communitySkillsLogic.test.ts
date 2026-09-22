import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { ApiError } from '~/lib/api-error'
import { urls } from '~/scenes/urls'
import { initKeaTests } from '~/test/init'

import { communitySkillsLogic } from './communitySkillsLogic'
import { communitySkillsInstallCreate, communitySkillsList } from './generated/api'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { error: jest.fn(), success: jest.fn(), info: jest.fn() },
}))

jest.mock('./generated/api', () => ({
    communitySkillsInstallCreate: jest.fn(),
    communitySkillsList: jest.fn(),
    communitySkillsVoteCreate: jest.fn(),
}))

const mockList = communitySkillsList as jest.MockedFunction<typeof communitySkillsList>
const mockInstall = communitySkillsInstallCreate as jest.MockedFunction<typeof communitySkillsInstallCreate>

describe('communitySkillsLogic', () => {
    let logic: ReturnType<typeof communitySkillsLogic.build>

    beforeEach(() => {
        jest.clearAllMocks()
        initKeaTests()
        mockList.mockResolvedValue({ results: [], count: 0 })
    })

    afterEach(() => {
        logic?.unmount()
    })

    it('ignores a trust tier the API does not define', async () => {
        logic = communitySkillsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSkillsSuccess'])

        router.actions.push(urls.communitySkills(), { trust_tier: 'platinum' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filters.trust_tier).toBe('')
        expect(mockList).toHaveBeenLastCalledWith(expect.anything(), expect.objectContaining({ trust_tier: undefined }))
    })

    it.each([
        [
            'the backend explanation when there is one',
            new ApiError('Bad request', 400, undefined, {
                detail: 'A skill named "make-pr" is already installed in your project.',
            }),
            'A skill named "make-pr" is already installed in your project.',
        ],
        ['generic copy otherwise', new Error('network down'), 'Could not install the skill. Try again in a moment.'],
    ])('failing to install reports %s', async (_name, error, expectedMessage) => {
        mockInstall.mockRejectedValue(error)
        logic = communitySkillsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSkillsSuccess'])

        logic.actions.installSkill('make-pr')
        await expectLogic(logic).toDispatchActions(['installSkillFailure'])

        expect(lemonToast.error).toHaveBeenCalledWith(expectedMessage)
    })
})
