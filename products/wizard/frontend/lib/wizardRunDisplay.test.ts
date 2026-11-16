import type { WizardRunApi } from '../generated/api.schemas'
import {
    WizardRunProgressStep,
    wizardGithubRepositoryUrl,
    wizardRunCanCancel,
    selectWizardInstallRun,
    wizardRunFailureStage,
    wizardRunProgressStates,
    wizardRunProgressStep,
} from './wizardRunDisplay'

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
        ['artifact_creation_failed', 'creating_artifacts'],
        ['PHW_CLI_BAD_ARGS', 'executing_wizard'],
        [null, 'executing_wizard'],
    ])('derives the failure stage from error code %s', (errorCode, expectedStage) => {
        const run = makeRun({ status: 'failed', error_code: errorCode, stage: null })

        expect(wizardRunFailureStage(run)).toBe(expectedStage)
    })

    test('has no stage for a timeout, which can hit any step', () => {
        const run = makeRun({ status: 'failed', error_code: 'timeout', stage: null })

        expect(wizardRunFailureStage(run)).toBeNull()
    })

    test('prefers the current stage when the run reports one', () => {
        const run = makeRun({ status: 'failed', error_code: 'PHW_CLI_BAD_ARGS', stage: 'creating_artifacts' })

        expect(wizardRunFailureStage(run)).toBe('creating_artifacts')
    })
})

describe('wizardRunProgressStep', () => {
    test.each([
        ['created', null, null, WizardRunProgressStep.Starting],
        ['running', null, 'preparing_workspace', WizardRunProgressStep.PreparingWorkspace],
        ['running', null, 'executing_wizard', WizardRunProgressStep.ExecutingWizard],
        ['failed', 'artifact_creation_failed', null, WizardRunProgressStep.CreatingArtifacts],
        ['completed', null, null, null],
        ['cancelled', null, null, null],
    ])('maps %s with stage %s/%s to %s', (status, errorCode, stage, expected) => {
        const run = makeRun({
            status: status as WizardRunApi['status'],
            error_code: errorCode,
            stage: stage as WizardRunApi['stage'],
        })

        expect(wizardRunProgressStep(run)).toBe(expected)
    })
})

describe('wizardRunProgressStates', () => {
    test('marks completed steps, the current step, and pending steps', () => {
        const run = makeRun({ status: 'running', stage: 'executing_wizard' })

        expect(wizardRunProgressStates(run)).toEqual({
            [WizardRunProgressStep.Starting]: 'complete',
            [WizardRunProgressStep.PreparingWorkspace]: 'complete',
            [WizardRunProgressStep.ExecutingWizard]: 'active',
            [WizardRunProgressStep.CreatingArtifacts]: 'pending',
        })
    })

    test('marks the failure step and leaves later steps pending', () => {
        const run = makeRun({ status: 'failed', error_code: 'artifact_creation_failed' })

        expect(wizardRunProgressStates(run)).toEqual({
            [WizardRunProgressStep.Starting]: 'complete',
            [WizardRunProgressStep.PreparingWorkspace]: 'complete',
            [WizardRunProgressStep.ExecutingWizard]: 'complete',
            [WizardRunProgressStep.CreatingArtifacts]: 'failed',
        })
    })
})

describe('selectWizardInstallRun', () => {
    test('shows the newest run regardless of environment or status', () => {
        const completedCloud = makeRun({
            id: 'cloud-completed',
            status: 'completed',
            environment: 'cloud',
            created_at: '2026-09-23T10:00:00Z',
        })
        const runningLocal = makeRun({
            id: 'local-running',
            status: 'running',
            environment: 'local',
            created_at: '2026-09-23T10:05:00Z',
        })

        expect(selectWizardInstallRun([completedCloud, runningLocal], '2026-09-23T09:00:00Z')).toBe(runningLocal)
        expect(selectWizardInstallRun([runningLocal, completedCloud], '2026-09-23T09:00:00Z')).toBe(runningLocal)
    })

    test('returns the newest completed run when that is all there is', () => {
        const run = makeRun({
            id: 'local-completed',
            status: 'completed',
            environment: 'local',
            created_at: '2026-09-23T10:00:00Z',
        })

        expect(selectWizardInstallRun([run], '2026-09-23T09:00:00Z')).toBe(run)
    })

    test('ignores runs created before the cutoff', () => {
        const oldRun = makeRun({
            id: 'old-run',
            created_at: '2026-09-23T09:00:00Z',
        })
        const recentRun = makeRun({
            id: 'recent-run',
            created_at: '2026-09-23T10:00:00Z',
        })

        expect(selectWizardInstallRun([recentRun, oldRun], '2026-09-23T09:30:00Z')).toBe(recentRun)
        expect(selectWizardInstallRun([oldRun], '2026-09-23T09:30:00Z')).toBeNull()
    })

    test('returns null when there are no runs', () => {
        expect(selectWizardInstallRun([], '2026-09-23T09:00:00Z')).toBeNull()
    })

    test('ignores audit programs and compares creation time, not update time, against the saved run', () => {
        const saved = makeRun({ id: 'saved', created_at: '2026-09-23T10:00:00Z' })
        const older = makeRun({ id: 'older', created_at: '2026-09-23T09:30:00Z', updated_at: '2026-09-23T11:00:00Z' })
        const audit = makeRun({
            ...saved,
            id: 'audit',
            program: { ...saved.program, id: 'analytics-audit' },
            created_at: '2026-09-23T12:00:00Z',
        })
        expect(selectWizardInstallRun([audit, older, saved], '2026-09-23T09:00:00Z', saved)).toBe(saved)
        expect(selectWizardInstallRun([audit, older], '2026-09-23T09:00:00Z', saved)).toBeNull()

        const newer = makeRun({ id: 'newer', created_at: '2026-09-23T10:30:00+00:00' })
        expect(selectWizardInstallRun([saved, newer], '2026-09-23T09:00:00Z', saved)).toBe(newer)
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
        ['local runs cannot be stopped from the browser', 'running', 7, 7, false, 'local'],
    ])('%s', (_label, status, createdById, currentUserId, expected, environment = 'cloud') => {
        const run = makeRun({
            status: status as WizardRunApi['status'],
            created_by_id: createdById,
            environment: environment as WizardRunApi['environment'],
        })

        expect(wizardRunCanCancel(run, currentUserId)).toBe(expected)
    })
})
