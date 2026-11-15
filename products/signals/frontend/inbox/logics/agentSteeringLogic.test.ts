import { expectLogic } from 'kea-test-utils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { agentSteeringLogic } from './agentSteeringLogic'

describe('agentSteeringLogic', () => {
    let logic: ReturnType<typeof agentSteeringLogic.build>
    let posted: unknown[]
    let config: Record<string, string>

    beforeEach(() => {
        initKeaTests()
        posted = []
        config = {
            scout_instructions: 'Focus on onboarding.',
            research_instructions: 'Check intent.',
            implementation_instructions: 'Open draft PRs.',
        }
        useMocks({
            get: { '/api/projects/:id/signals/config/': () => [200, config] },
            post: {
                '/api/projects/:id/signals/config/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, string>
                    posted.push(body)
                    config = { ...config, ...body }
                    return [200, config]
                },
            },
        })
        logic = agentSteeringLogic()
        logic.mount()
    })

    afterEach(() => logic.unmount())

    it('keeps drafts separate when switching roles and only saves or clears the selected role', async () => {
        await expectLogic(logic).toFinishAllListeners()
        expect(logic.values.selectedRole).toBe('research')
        expect(logic.values.dirtyRoles).toEqual([])
        logic.actions.setDraft('implementation', 'Open draft PRs.')
        expect(logic.values.dirtyRoles).toEqual([])
        logic.actions.setDraft('scout', 'Inspect new user sessions.')
        logic.actions.selectRole('research')
        expect(logic.values.instructions).toBe('Check intent.')
        logic.actions.setDraft('research', '')
        expect(logic.values.dirtyRoles).toEqual(['scout', 'research'])

        await expectLogic(logic, () => logic.actions.submitInstructions())
            .toDispatchActions(['saveSteeringInstructionsSuccess'])
            .toMatchValues({ instructions: '', instructionsDirty: false })
        expect(posted).toEqual([{ research_instructions: '' }])
        expect(logic.values.dirtyRoles).toEqual(['scout'])

        logic.actions.selectRole('scout')
        expect(logic.values.instructions).toBe('Inspect new user sessions.')
        logic.actions.discardDraft('scout')
        expect(logic.values.dirtyRoles).toEqual([])
        expect(logic.values.instructions).toBe('Focus on onboarding.')
        logic.actions.selectRole('implementation')
        expect(logic.values.instructions).toBe('Open draft PRs.')
    })

    it('prevents double submission and preserves another role draft during a save', async () => {
        await expectLogic(logic).toFinishAllListeners()
        let finishSave!: () => void
        const saving = new Promise<void>((resolve) => {
            finishSave = resolve
        })
        useMocks({
            post: {
                '/api/projects/:id/signals/config/': async ({ request }) => {
                    const body = (await request.json()) as Record<string, string>
                    posted.push(body)
                    await saving
                    return [200, { ...config, ...body }]
                },
            },
        })
        logic.actions.selectRole('scout')
        logic.actions.setDraft('scout', 'New scout rules.')
        logic.actions.submitInstructions()
        logic.actions.submitInstructions()
        logic.actions.selectRole('research')
        logic.actions.setDraft('research', 'New research rules.')
        expect(logic.values.steeringConfigLoading).toBe(true)
        finishSave()
        await expectLogic(logic)
            .toFinishAllListeners()
            .toMatchValues({ instructions: 'New research rules.', instructionsDirty: true })
        expect(posted).toEqual([{ scout_instructions: 'New scout rules.' }])
        logic.actions.selectRole('scout')
        expect(logic.values.instructionsDirty).toBe(false)
    })

    it('retains the draft after a failed save and allows retrying', async () => {
        await expectLogic(logic).toFinishAllListeners()
        useMocks({ post: { '/api/projects/:id/signals/config/': () => [500, { detail: 'Unavailable' }] } })
        logic.actions.selectRole('scout')
        logic.actions.setDraft('scout', 'Retry these rules.')
        await expectLogic(logic, () => logic.actions.submitInstructions())
            .toDispatchActions(['saveSteeringInstructionsFailure'])
            .toMatchValues({
                instructions: 'Retry these rules.',
                instructionsDirty: true,
                steeringConfigLoading: false,
            })
        useMocks({
            post: {
                '/api/projects/:id/signals/config/': () => [
                    200,
                    { ...config, scout_instructions: 'Retry these rules.' },
                ],
            },
        })
        await expectLogic(logic, () => logic.actions.submitInstructions())
            .toDispatchActions(['saveSteeringInstructionsSuccess'])
            .toMatchValues({ instructions: 'Retry these rules.', instructionsDirty: false })
        expect(logic.values.steeringConfig?.scout_instructions).toBe('Retry these rules.')
    })
})
