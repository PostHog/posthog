import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { ApiError } from '~/lib/api-error'
import { urls } from '~/scenes/urls'
import { initKeaTests } from '~/test/init'

import { decodeScoutCreateTemplate } from 'products/signals/frontend/inbox/utils/scoutTemplateDeepLink'

import { communitySkillsLogic } from './communitySkillsLogic'
import { communitySkillsInstallCreate, communitySkillsList, communitySkillsRenderCreate } from './generated/api'

jest.mock('lib/lemon-ui/LemonToast/LemonToast', () => ({
    lemonToast: { error: jest.fn(), success: jest.fn(), info: jest.fn() },
}))

jest.mock('./generated/api', () => ({
    communitySkillsInstallCreate: jest.fn(),
    communitySkillsList: jest.fn(),
    communitySkillsRenderCreate: jest.fn(),
    communitySkillsVoteCreate: jest.fn(),
}))

const mockList = communitySkillsList as jest.MockedFunction<typeof communitySkillsList>
const mockInstall = communitySkillsInstallCreate as jest.MockedFunction<typeof communitySkillsInstallCreate>
const mockRender = communitySkillsRenderCreate as jest.MockedFunction<typeof communitySkillsRenderCreate>

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

    it('hands a scout to the create form prefilled, without creating anything', async () => {
        mockRender.mockResolvedValue({
            slug: 'signals-scout-feed',
            kind: 'scout',
            name: 'Feed scout',
            description: 'Watch a feed for problems.',
            body: `# Scout\n${'x'.repeat(20_000)}`,
            scout_config: { run_interval_minutes: 720, emit: false },
            variable_bindings: {},
        })
        logic = communitySkillsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSkillsSuccess'])

        logic.actions.setUpScout('signals-scout-feed')
        await expectLogic(logic).toDispatchActions(['setUpScoutSuccess'])

        expect(mockInstall).not.toHaveBeenCalled()
        expect(router.values.location.pathname).toContain('/inbox/config')
        expect(decodeScoutCreateTemplate(router.values.hashParams.createScout)).toEqual({
            display_name: 'Feed scout',
            description: 'Watch a feed for problems.',
            body: `# Scout\n${'x'.repeat(20_000)}`,
            config: { run_interval_minutes: 720, emit: false, mcp_gateway_server_ids: [] },
        })
        expect(String(router.values.hashParams.createScout)).toHaveLength(43)
    })

    it('refuses an entry the catalog no longer calls a scout', async () => {
        // The catalog syncs hourly, so an open card can outlive the kind it was rendered from.
        mockRender.mockResolvedValue({
            slug: 'signals-scout-feed',
            kind: 'skill',
            name: 'Feed scout',
            description: 'Watch a feed for problems.',
            body: '# Scout',
            scout_config: {},
            variable_bindings: {},
        })
        logic = communitySkillsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSkillsSuccess'])

        logic.actions.setUpScout('signals-scout-feed')
        await expectLogic(logic).toDispatchActions(['setUpScoutFailure'])

        expect(router.values.location.pathname).not.toContain('/inbox/config')
        expect(lemonToast.error).toHaveBeenCalledWith(
            'This entry is no longer a scout. Refresh the store and try again.'
        )
    })

    it('lets the scout asked for last win when an earlier render finishes after it', async () => {
        const scout = (slug: string, name: string): any => ({
            slug,
            kind: 'scout',
            name,
            description: `${name} description`,
            body: `# ${name}`,
            scout_config: {},
            variable_bindings: {},
        })
        let finishFirst: (value: any) => void = () => {}
        mockRender
            .mockImplementationOnce(() => new Promise((resolve) => (finishFirst = resolve)))
            .mockImplementationOnce(() => Promise.resolve(scout('signals-scout-second', 'Second scout')))
        logic = communitySkillsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSkillsSuccess'])

        logic.actions.setUpScout('signals-scout-first')
        logic.actions.setUpScout('signals-scout-second')
        await expectLogic(logic).toDispatchActions(['setUpScoutSuccess'])

        finishFirst(scout('signals-scout-first', 'First scout'))
        await expectLogic(logic).toFinishAllListeners()

        // The slower first render must not replace the form the person asked for last.
        expect(decodeScoutCreateTemplate(router.values.hashParams.createScout)).toMatchObject({
            display_name: 'Second scout',
        })
        expect(logic.values.settingUpSlugs['signals-scout-first']).toBe(false)
    })

    it('uses top rated as the default scout order', async () => {
        logic = communitySkillsLogic()
        logic.mount()
        await expectLogic(logic).toDispatchActions(['loadSkillsSuccess'])

        router.actions.push(urls.communitySkills(), { kind: 'scout' })
        await expectLogic(logic).toFinishAllListeners()

        expect(logic.values.filters.order_by).toBe('-vote_count')
        expect(mockList).toHaveBeenLastCalledWith(
            expect.anything(),
            expect.objectContaining({ order_by: '-vote_count' })
        )
    })
})
