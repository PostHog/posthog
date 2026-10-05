import { expectLogic } from 'kea-test-utils'

import { initKeaTests } from '~/test/init'

import {
    integrationsGithubAssigneesRetrieve,
    integrationsGitlabMembersRetrieve,
    integrationsJiraAssignableUsersRetrieve,
    integrationsLinearTeamMembersRetrieve,
} from 'products/integrations/frontend/generated/api'

import { ExternalIssueAssigneeKind, externalIssueAssigneesLogic } from './externalIssueAssigneesLogic'

jest.mock('products/integrations/frontend/generated/api', () => ({
    integrationsGithubAssigneesRetrieve: jest.fn(),
    integrationsGitlabMembersRetrieve: jest.fn(),
    integrationsJiraAssignableUsersRetrieve: jest.fn(),
    integrationsLinearTeamMembersRetrieve: jest.fn(),
}))

const USERS = [{ id: 'u1', name: 'Ada' }]

const PROVIDER_CALLS: Record<ExternalIssueAssigneeKind, jest.Mock> = {
    linear: jest.mocked(integrationsLinearTeamMembersRetrieve),
    github: jest.mocked(integrationsGithubAssigneesRetrieve),
    gitlab: jest.mocked(integrationsGitlabMembersRetrieve),
    jira: jest.mocked(integrationsJiraAssignableUsersRetrieve),
}

describe('externalIssueAssigneesLogic', () => {
    let logic: ReturnType<typeof externalIssueAssigneesLogic.build>

    beforeEach(() => {
        initKeaTests()
        Object.values(PROVIDER_CALLS).forEach((call) => call.mockReset().mockResolvedValue({ users: USERS }))
    })

    afterEach(() => logic?.unmount())

    test.each([
        ['linear', 'team-id', { team_id: 'team-id' }],
        ['github', 'posthog', { repository: 'posthog' }],
        ['jira', 'ENG', { project_key: 'ENG' }],
    ] as const)('%s sends the chosen scope as its lookup parameter', async (kind, scope, params) => {
        logic = externalIssueAssigneesLogic({ integrationId: 1, kind, scope })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadAssigneesSuccess'])
            .toMatchValues({
                assignees: { users: USERS },
            })
        expect(PROVIDER_CALLS[kind]).toHaveBeenCalledWith(expect.any(String), 1, params)
    })

    test.each(['linear', 'github', 'jira'] as const)('%s waits for a scope before calling the API', async (kind) => {
        logic = externalIssueAssigneesLogic({ integrationId: 1, kind, scope: null })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadAssigneesSuccess'])
            .toMatchValues({
                assignees: { users: [] },
            })
        expect(PROVIDER_CALLS[kind]).not.toHaveBeenCalled()
    })

    it('keeps the reconnect flag so the field can ask for a reconnect', async () => {
        PROVIDER_CALLS.jira.mockResolvedValue({ users: [], reconnect_required: true })
        logic = externalIssueAssigneesLogic({ integrationId: 1, kind: 'jira', scope: 'ENG' })
        logic.mount()

        await expectLogic(logic)
            .toDispatchActions(['loadAssigneesSuccess'])
            .toMatchValues({
                assignees: { users: [], reconnect_required: true },
            })
    })

    it('leaves assignees unresolved when the lookup fails', async () => {
        PROVIDER_CALLS.gitlab.mockRejectedValue(new Error('boom'))
        logic = externalIssueAssigneesLogic({ integrationId: 1, kind: 'gitlab', scope: null })
        logic.mount()

        await expectLogic(logic).toDispatchActions(['loadAssigneesFailure']).toMatchValues({
            assignees: null,
            assigneesLoading: false,
        })
    })
})
