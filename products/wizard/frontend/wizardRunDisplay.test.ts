import type { WizardRunApi } from './generated/api.schemas'
import { wizardGithubRepositoryUrl, wizardRunCanCancel, wizardRunFailureStage } from './wizardRunDisplay'

function makeRun(overrides: Partial<WizardRunApi>): WizardRunApi {
    return {
        id: 'run-1',
        team_id: 1,
        created_by_id: 1,
        environment: 'cloud',
        workspace: { type: 'git_repository', repository: 'posthog/posthog' },
        program: {
            id: 'posthog-integration',
            name: 'PostHog integration',
            description: 'Set up PostHog',
            wizard_version: '2.67.0',
            command: [],
            tags: [],
            required_programs: [],
            supported_environments: ['local', 'cloud'],
        },
        status: 'failed',
        error_code: null,
        error_message: null,
        stage: null,
        created_at: '2026-08-28T10:00:00Z',
        started_at: null,
        finished_at: null,
        workspace_type: 'git_repository',
        program_id: 'posthog-integration',
        ...overrides,
    } as WizardRunApi
}

describe('wizardRunFailureStage', () => {
    test.each([
        ['dispatch_failed', 'dispatching'],
        ['provisioning_failed', 'provisioning'],
        ['repository_access_failed', 'preparing_workspace'],
        ['workspace_preparation_failed', 'preparing_workspace'],
        ['timeout', 'executing_wizard'],
        ['artifact_creation_failed', 'creating_artifacts'],
        ['PHW_CLI_BAD_ARGS', 'executing_wizard'],
        [null, 'executing_wizard'],
    ])('derives the failure stage from error code %s', (errorCode, expectedStage) => {
        const run = makeRun({ status: 'failed', error_code: errorCode, stage: null })

        expect(wizardRunFailureStage(run)).toBe(expectedStage)
    })

    test('prefers the current stage when the run reports one', () => {
        const run = makeRun({ status: 'failed', error_code: 'PHW_CLI_BAD_ARGS', stage: 'creating_artifacts' })

        expect(wizardRunFailureStage(run)).toBe('creating_artifacts')
    })
})

describe('wizardGithubRepositoryUrl', () => {
    test('builds the GitHub URL for a repository', () => {
        expect(wizardGithubRepositoryUrl('posthog/posthog')).toBe('https://github.com/posthog/posthog')
    })
})

describe('wizardRunCanCancel', () => {
    test.each([
        ['creator sees cancel on an active run', 'running', 7, 7, true],
        ['teammate cannot cancel someone else’s run', 'running', 7, 9, false],
        ['no cancel once the run is terminal', 'completed', 7, 7, false],
        ['runs without a creator hide cancel from everyone', 'running', null, 7, false],
        ['unknown current user hides cancel', 'running', 7, null, false],
    ])('%s', (_label, status, createdById, currentUserId, expected) => {
        const run = makeRun({ status: status as WizardRunApi['status'], created_by_id: createdById })

        expect(wizardRunCanCancel(run, currentUserId)).toBe(expected)
    })
})
