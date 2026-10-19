import { MOCK_DEFAULT_ORGANIZATION, MOCK_DEFAULT_USER } from 'lib/api.mock'

import { router } from 'kea-router'
import { expectLogic } from 'kea-test-utils'

import { organizationLogic } from 'scenes/organizationLogic'
import { userLogic } from 'scenes/userLogic'

import { useMocks } from '~/mocks/jest'
import { initKeaTests } from '~/test/init'
import { AccessControlLevel, AppContext, HogFunctionTemplateType, UserType } from '~/types'

import { workflowDataSuggestionsBuildForEvents } from '../generated/api'
import {
    DESTINATION_WORKFLOW_SUGGESTION_SEEN_KEY,
    destinationWorkflowSuggestionLogic,
} from './destinationWorkflowSuggestionLogic'

jest.mock('../generated/api', () => ({
    workflowDataSuggestionsBuildForEvents: jest.fn(),
}))

const template = (id: string): HogFunctionTemplateType =>
    ({ id, type: 'destination', name: id, inputs_schema: [] }) as unknown as HogFunctionTemplateType

describe('destinationWorkflowSuggestionLogic', () => {
    let logic: ReturnType<typeof destinationWorkflowSuggestionLogic.build>

    beforeEach(() => {
        useMocks({ patch: { '/api/users/@me/product_intro_seen': {} } })
    })

    const setUp = ({
        seen = {},
        workflowAccess = AccessControlLevel.Editor,
        aiApproved = true,
    }: {
        seen?: Record<string, boolean>
        workflowAccess?: AccessControlLevel
        aiApproved?: boolean
    } = {}): void => {
        initKeaTests()
        window.POSTHOG_APP_CONTEXT = {
            ...window.POSTHOG_APP_CONTEXT,
            resource_access_control: { hog_flow: workflowAccess },
        } as unknown as AppContext
        userLogic.mount()
        userLogic.actions.loadUserSuccess({ ...MOCK_DEFAULT_USER, has_seen_product_intro_for: seen } as UserType)
        organizationLogic.mount()
        organizationLogic.actions.loadCurrentOrganizationSuccess({
            ...MOCK_DEFAULT_ORGANIZATION,
            is_ai_data_processing_approved: aiApproved,
        })
        logic = destinationWorkflowSuggestionLogic()
        logic.mount()
    }

    it.each([
        ['asks for an email tool', 'template-customerio', {}, true],
        ['skips a destination that is not an email tool', 'template-webhook', {}, false],
        ['skips team chat, which Workflows does not replace', 'template-slack', {}, false],
        [
            'skips a user who answered before',
            'template-customerio',
            { seen: { [DESTINATION_WORKFLOW_SUGGESTION_SEEN_KEY]: true } },
            false,
        ],
        [
            'skips a user who cannot edit workflows',
            'template-customerio',
            { workflowAccess: AccessControlLevel.Viewer },
            false,
        ],
    ])('%s', (_label, templateId, setup, expected) => {
        setUp(setup)

        expect(logic.values.shouldSuggestWorkflow(template(templateId))).toBe(expected)
    })

    it.each([
        ['builds workflows for picked events', ['signed_up'], true, true],
        ['only points to Workflows with just the default events', [], true, false],
        ['only points to Workflows when the organization has not approved AI', ['signed_up'], false, false],
    ])('%s', (_label, events, aiApproved, canBuild) => {
        setUp({ aiApproved })
        logic.actions.openSuggestion(template('template-customerio'), events, jest.fn())

        expect(logic.values.canBuildWorkflows).toBe(canBuild)
    })

    it.each([
        [
            'saves the destination and remembers the answer after continue',
            'continueWithDestination',
            true,
            /\/pipeline$/,
        ],
        ['opens a new workflow and remembers the answer', 'openWorkflowEditor', true, /\/workflows\/new\/workflow$/],
        ['keeps the form and asks again after the modal is closed', 'closeSuggestion', false, /\/pipeline$/],
    ] as const)('%s', async (_label, action, chosen, path) => {
        setUp()
        router.actions.push('/pipeline')
        const onContinue = jest.fn()
        logic.actions.openSuggestion(template('template-customerio'), ['signed_up'], onContinue)

        const seenAction = userLogic.actionCreators.updateHasSeenProductIntroFor(
            DESTINATION_WORKFLOW_SUGGESTION_SEEN_KEY
        )
        const expectation = expectLogic(logic, () => {
            logic.actions[action]()
        }).toDispatchActions(chosen ? [seenAction, 'resetSuggestion'] : ['resetSuggestion'])
        if (!chosen) {
            expectation.toNotHaveDispatchedActions([seenAction])
        }
        await expectation.toMatchValues({ template: null, dismissed: chosen })
        expect(onContinue).toHaveBeenCalledTimes(action === 'continueWithDestination' ? 1 : 0)
        expect(router.values.location.pathname).toMatch(path)
    })

    it.each([
        [
            'opens the built draft and remembers the answer',
            () => Promise.resolve({ status: 'ready', workflow_ids: ['workflow-1'] }),
            /\/workflows\/workflow-1\/workflow$/,
            { dismissed: true, buildState: null },
        ],
        [
            'keeps the modal open to retry when the build fails',
            () => Promise.resolve({ status: 'failed', workflow_ids: [] }),
            /\/pipeline$/,
            { dismissed: false, buildState: 'failed', canBuildWorkflows: true },
        ],
        [
            'offers the manual workflow when the API refuses to build',
            () => Promise.reject({ status: 403 }),
            /\/pipeline$/,
            { dismissed: false, buildState: null, canBuildWorkflows: false },
        ],
    ] as const)('%s', async (_label, response, path, values) => {
        setUp()
        router.actions.push('/pipeline')
        jest.mocked(workflowDataSuggestionsBuildForEvents).mockImplementation(response as any)
        logic.actions.openSuggestion(template('template-customerio'), ['signed_up', 'trial_started'], jest.fn())
        logic.actions.toggleEvent('trial_started')

        await expectLogic(logic, () => {
            logic.actions.createWorkflows()
        })
            .toFinishAllListeners()
            .toMatchValues(values)

        expect(jest.mocked(workflowDataSuggestionsBuildForEvents)).toHaveBeenCalledWith(expect.any(String), {
            events: ['signed_up'],
            retry: true,
        })
        expect(router.values.location.pathname).toMatch(path)
    })
})
