import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { maxMocks } from 'scenes/max/testUtils'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'

import { newWorkflowLogic } from './newWorkflowLogic'
import { TRIGGER_PREFILL_PARAM } from './workflowTriggerPrefill'

const AI_FIRST_FLAGS = [
    FEATURE_FLAGS.WORKFLOWS_AI_FIRST_NEW,
    FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN,
    FEATURE_FLAGS.PHAI_SANDBOX_MODE,
]

describe('newWorkflowLogic', () => {
    const setFlags = (flags: string[], variants: Record<string, string | boolean> = {}): void => {
        featureFlagLogic.actions.setFeatureFlags(flags, {
            ...Object.fromEntries(flags.map((flag) => [flag, true])),
            ...variants,
        })
    }

    beforeEach(() => {
        useMocks(maxMocks)
        initKeaTests()
    })

    describe('AI-first new workflow', () => {
        // The experiment hinges on the flag-on path skipping the modal and the flag-off path staying
        // byte-identical; a regression either way silently poisons the experiment's arms.
        it.each([
            { name: 'flag on', flags: AI_FIRST_FLAGS, routed: true },
            {
                name: 'flag off',
                flags: [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE],
                routed: false,
            },
            { name: 'scene integration off', flags: [FEATURE_FLAGS.WORKFLOWS_AI_FIRST_NEW], routed: false },
        ])('startNewWorkflow routes to the composer only with $name', async ({ flags, routed }) => {
            setFlags(flags)
            const logic = newWorkflowLogic()
            logic.mount()
            router.actions.push('/workflows', {}, {})

            await expectLogic(logic, () => {
                logic.actions.startNewWorkflow()
            }).toFinishAllListeners()

            expect(logic.values.newWorkflowModalVisible).toBe(!routed)
            expect(removeProjectIdIfPresent(router.values.location.pathname)).toBe(
                routed ? '/workflows/new/workflow' : '/workflows'
            )
        })

        // Template and prefill deep links, and the escape hatch's own route, must keep landing in the
        // editor, otherwise the composer swallows a starting point the user already chose.
        it.each([
            { name: 'plain new URL', search: {}, available: true },
            { name: 'a template', search: { templateId: 'tpl-1' }, available: false },
            { name: 'a template edit', search: { editTemplateId: 'tpl-1' }, available: false },
            { name: 'a trigger prefill', search: { [TRIGGER_PREFILL_PARAM]: 'x' }, available: false },
            { name: 'the editor mode param', search: { mode: 'editor' }, available: false },
        ])('aiComposerAvailable is $available for $name', ({ search, available }) => {
            setFlags(AI_FIRST_FLAGS)
            const logic = newWorkflowLogic()
            logic.mount()

            router.actions.push('/workflows/new/workflow', search, {})

            expect(logic.values.aiComposerAvailable).toBe(available)
        })

        it('createEmptyWorkflow marks the editor route so the composer does not render again', async () => {
            setFlags(AI_FIRST_FLAGS)
            const logic = newWorkflowLogic()
            logic.mount()
            router.actions.push('/workflows/new/workflow', {}, {})

            await expectLogic(logic, () => {
                logic.actions.openEditorFromAiComposer()
                logic.actions.createEmptyWorkflow()
            }).toFinishAllListeners()

            expect(router.values.searchParams).toEqual({ mode: 'editor' })
            expect(logic.values.aiComposerAvailable).toBe(false)
        })
    })

    describe('urlToAction', () => {
        it('opens modal when navigating to /workflows with #newWorkflow hash param', async () => {
            const logic = newWorkflowLogic()
            logic.mount()

            await expectLogic(logic, () => {
                router.actions.push('/workflows', {}, { newWorkflow: 'modal' })
            })
                .toDispatchActions(['showNewWorkflowModal'])
                .toMatchValues({
                    newWorkflowModalVisible: true,
                })
        })

        it('opens modal when navigating to /workflows/:tab with #newWorkflow hash param', async () => {
            const logic = newWorkflowLogic()
            logic.mount()

            await expectLogic(logic, () => {
                router.actions.push('/workflows/library', {}, { newWorkflow: 'modal' })
            })
                .toDispatchActions(['showNewWorkflowModal'])
                .toMatchValues({
                    newWorkflowModalVisible: true,
                })
        })

        it('does not open modal when hash param is missing', async () => {
            const logic = newWorkflowLogic()
            logic.mount()

            await expectLogic(logic, () => {
                router.actions.push('/workflows', {}, {})
            }).toNotHaveDispatchedActions(['showNewWorkflowModal'])

            expect(logic.values.newWorkflowModalVisible).toBe(false)
        })
    })

    describe('actionToUrl', () => {
        it('adds newWorkflow hash param when showing modal', () => {
            const logic = newWorkflowLogic()
            logic.mount()

            router.actions.push('/workflows', {}, {})
            logic.actions.showNewWorkflowModal()

            expect(router.values.hashParams).toHaveProperty('newWorkflow', 'modal')
        })

        it('removes newWorkflow hash param when hiding modal', () => {
            const logic = newWorkflowLogic()
            logic.mount()

            router.actions.push('/workflows', {}, { newWorkflow: 'modal' })
            logic.actions.hideNewWorkflowModal()

            expect(router.values.hashParams).not.toHaveProperty('newWorkflow')
        })
    })
})
