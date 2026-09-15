import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'
import posthog from 'posthog-js'

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
        // `exposed` is the experiment's own measurement: the click is the decision point, so it records
        // exposure for both arms, and records nothing for a click the composer could never answer.
        it.each([
            { name: 'flag on', flags: AI_FIRST_FLAGS, routed: true, exposed: true },
            {
                name: 'flag off',
                flags: [FEATURE_FLAGS.PHAI_SCENE_AUTO_OPEN, FEATURE_FLAGS.PHAI_SANDBOX_MODE],
                routed: false,
                exposed: true,
            },
            {
                name: 'scene integration off',
                flags: [FEATURE_FLAGS.WORKFLOWS_AI_FIRST_NEW],
                routed: false,
                exposed: false,
            },
        ])('startNewWorkflow routes to the composer only with $name', async ({ flags, routed, exposed }) => {
            setFlags(flags)
            const recordExposure = jest.spyOn(posthog, 'getFeatureFlag').mockReturnValue(undefined)
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
            // The composer answers a marked entry only, so the click has to mark its own route.
            expect(router.values.searchParams).toEqual(routed ? { mode: 'ai' } : {})
            expect(recordExposure.mock.calls.map(([flag]) => flag)).toEqual(
                exposed ? [FEATURE_FLAGS.WORKFLOWS_AI_FIRST_NEW] : []
            )
            recordExposure.mockRestore()
        })

        // Template and prefill deep links, and the escape hatch's own route, must keep landing in the
        // editor, otherwise the composer swallows a starting point the user already chose.
        it.each([
            { name: 'an AI entry', path: '/workflows/new/workflow', search: { mode: 'ai' }, available: true },
            // Other products open the plain URL for a specific job and tell the person the editor is there.
            { name: 'a plain new URL', path: '/workflows/new/workflow', search: {}, available: false },
            {
                name: 'a template',
                path: '/workflows/new/workflow',
                search: { mode: 'ai', templateId: 'tpl-1' },
                available: false,
            },
            {
                name: 'a template edit',
                path: '/workflows/new/workflow',
                search: { mode: 'ai', editTemplateId: 'tpl-1' },
                available: false,
            },
            {
                name: 'a trigger prefill',
                path: '/workflows/new/workflow',
                search: { mode: 'ai', [TRIGGER_PREFILL_PARAM]: 'x' },
                available: false,
            },
            {
                name: 'the editor mode param',
                path: '/workflows/new/workflow',
                search: { mode: 'editor' },
                available: false,
            },
            // The editor scene reads this for every workflow it opens. An existing workflow must answer
            // false without reading the flag, or opening any editor joins the experiment's exposure.
            {
                name: 'an existing workflow',
                path: '/workflows/wf-1/workflow',
                search: { mode: 'ai' },
                available: false,
            },
        ])('aiComposerAvailable is $available for $name', ({ path, search, available }) => {
            setFlags(AI_FIRST_FLAGS)
            const logic = newWorkflowLogic()
            logic.mount()

            router.actions.push(path, search, {})

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
