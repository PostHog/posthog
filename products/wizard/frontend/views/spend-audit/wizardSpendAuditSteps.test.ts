import type { WizardRunApi, WizardRunTaskApi } from '../../generated/api.schemas'
import { wizardSpendAuditStepStates } from './wizardSpendAuditSteps'

const run = (status: WizardRunApi['status'], stage: WizardRunApi['stage'] = 'executing_wizard'): WizardRunApi =>
    ({ status, stage, error_code: null }) as WizardRunApi
const task = (name: string, status: WizardRunTaskApi['status']): WizardRunTaskApi =>
    ({ name, status }) as WizardRunTaskApi

describe('wizardSpendAuditStepStates', () => {
    it.each([
        [
            'nothing reported before the sandbox runs',
            run('running', 'preparing_workspace'),
            [],
            ['pending', 'pending', 'pending', 'pending'],
        ],
        [
            'the audit as active once the program executes',
            run('running'),
            [],
            ['active', 'pending', 'pending', 'pending'],
        ],
        [
            'each step from the task that names it',
            run('running'),
            [
                task('Audit the PostHog setup', 'completed'),
                task('Write the audit notebook', 'completed'),
                task('Open pull request: trim autocapture', 'completed'),
                task('Open pull request: drop unused flags', 'running'),
                task('Create unused events dashboard', 'created'),
            ],
            ['complete', 'complete', 'active', 'pending'],
        ],
        [
            'everything complete when the run completes',
            run('completed', null),
            [task('Audit', 'failed')],
            ['complete', 'complete', 'complete', 'complete'],
        ],
        [
            'the failed task as failed and later steps as pending',
            run('failed'),
            [task('Audit the PostHog setup', 'completed'), task('Write the audit notebook', 'failed')],
            ['complete', 'failed', 'pending', 'pending'],
        ],
        [
            'the first open step as failed when a run fails without a failed task',
            run('failed'),
            [task('Audit the PostHog setup', 'completed')],
            ['complete', 'failed', 'pending', 'pending'],
        ],
        [
            'no failed step when a run is canceled',
            run('cancelled', null),
            [task('Audit the PostHog setup', 'completed')],
            ['complete', 'pending', 'pending', 'pending'],
        ],
    ])('shows %s', (_, givenRun, tasks, expected) => {
        expect(Object.values(wizardSpendAuditStepStates(givenRun, tasks))).toEqual(expected)
    })
})
