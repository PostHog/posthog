import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AppContext, HogFunctionTemplateType, UserType } from '~/types'

import { hogFlowsCreate } from '../generated/api'
import {
    DESTINATION_WORKFLOW_SUGGESTION_SEEN_KEY,
    destinationWorkflowSuggestionLogic,
} from './destinationWorkflowSuggestionLogic'

jest.mock('../generated/api', () => ({
    hogFlowsCreate: jest.fn(),
}))

const template = (id: string): HogFunctionTemplateType =>
    ({ id, type: 'destination', name: id, inputs_schema: [] }) as unknown as HogFunctionTemplateType

describe('destinationWorkflowSuggestionLogic', () => {
    let logic: ReturnType<typeof destinationWorkflowSuggestionLogic.build>

    beforeEach(() => {
        useMocks({ patch: { '/api/users/@me/product_intro_seen': {} } })
    })

    const setUp = (seen: Record<string, boolean>, workflowAccess: AccessControlLevel): void => {
        initKeaTests()
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: { hog_flow: workflowAccess },
        } as unknown as AppContext
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, has_seen_product_intro_for: seen } as UserType)
        logic = destinationWorkflowSuggestionLogic()
        logic.mount()
    }

    it.each([
        ['suggests it for a messaging destination', 'template-customerio', {}, AccessControlLevel.Editor, true],
        ['skips a destination that is not messaging', 'template-webhook', {}, AccessControlLevel.Editor, false],
        [
            'skips a user who answered before',
            'template-customerio',
            { [DESTINATION_WORKFLOW_SUGGESTION_SEEN_KEY]: true },
            AccessControlLevel.Editor,
            false,
        ],
        ['skips a user who cannot edit workflows', 'template-slack', {}, AccessControlLevel.Viewer, false],
    ])('%s', (_label, templateId, seen, workflowAccess, expected) => {
        setUp(seen, workflowAccess)

        expect(logic.values.shouldSuggestWorkflow(template(templateId))).toBe(expected)
    })

    it.each([
        ['remembers the answer after continuing with the destination', 'continueWithDestination', true],
        ['remembers the answer after creating the workflow', 'createWorkflow', true],
        ['asks again after the modal is closed', 'closeSuggestion', false],
    ] as const)('%s', async (_label, action, remembered) => {
        setUp({}, AccessControlLevel.Editor)
        jest.mocked(hogFlowsCreate).mockResolvedValue({ id: 'workflow-1' } as any)
        logic.actions.openSuggestion(template('template-customerio'), '/functions/new/template-customerio')

        const seenAction = userLogic.actionCreators.updateHasSeenProductIntroFor(
            DESTINATION_WORKFLOW_SUGGESTION_SEEN_KEY
        )
        const expectation = expectLogic(logic, () => {
            logic.actions[action]()
        }).toDispatchActions(remembered ? [seenAction, 'resetSuggestion'] : ['resetSuggestion'])
        if (!remembered) {
            expectation.toNotHaveDispatchedActions([seenAction])
        }
        await expectation.toMatchValues({ template: null })
    })

    it('leaves the user on the page they went to when they leave before the draft is saved', async () => {
        setUp({}, AccessControlLevel.Editor)
        let saveDraft: (workflow: { id: string }) => void = () => {}
        jest.mocked(hogFlowsCreate).mockReturnValue(new Promise((resolve) => (saveDraft = resolve)) as any)
        logic.actions.openSuggestion(template('template-customerio'), '/functions/new/template-customerio')
        logic.actions.createWorkflow()

        router.actions.push('/insights')
        logic.unmount()
        saveDraft({ id: 'workflow-1' })
        await new Promise((resolve) => setTimeout(resolve, 0))

        expect(router.values.location.pathname).toMatch(/\/insights$/)
    })
})
