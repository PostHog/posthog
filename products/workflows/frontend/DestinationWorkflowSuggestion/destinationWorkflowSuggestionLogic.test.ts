import { MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AppContext, HogFunctionTemplateType, UserType } from '~/types'

import {
    DESTINATION_WORKFLOW_SUGGESTION_SEEN_KEY,
    destinationWorkflowSuggestionLogic,
} from './destinationWorkflowSuggestionLogic'

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
        ['skips team chat, which Workflows does not replace', 'template-slack', {}, AccessControlLevel.Editor, false],
        [
            'skips a user who answered before',
            'template-customerio',
            { [DESTINATION_WORKFLOW_SUGGESTION_SEEN_KEY]: true },
            AccessControlLevel.Editor,
            false,
        ],
        ['skips a user who cannot edit workflows', 'template-customerio', {}, AccessControlLevel.Viewer, false],
    ])('%s', (_label, templateId, seen, workflowAccess, expected) => {
        setUp(seen, workflowAccess)

        expect(logic.values.shouldSuggestWorkflow(template(templateId))).toBe(expected)
    })

    it.each([
        [
            'goes to the destination and remembers the answer',
            'continueWithDestination',
            true,
            /\/functions\/new\/template-customerio$/,
        ],
        ['goes to the workflow templates and remembers the answer', 'openWorkflows', true, /\/workflows\/templates$/],
        ['stays on the list and asks again after the modal is closed', 'closeSuggestion', false, /\/pipeline$/],
    ] as const)('%s', async (_label, action, remembered, path) => {
        setUp({}, AccessControlLevel.Editor)
        router.actions.push('/pipeline')
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
        expect(router.values.location.pathname).toMatch(path)
    })
})
