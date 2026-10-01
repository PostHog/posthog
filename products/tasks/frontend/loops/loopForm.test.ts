import type { LoopDTOApi, LoopTriggerDTOApi } from '../generated/api.schemas'
import { compileCronSchedule, loopPatch, loopToFormValues, parseCronSchedule } from './loopForm'

function trigger(type: string, config: Record<string, unknown>, id = `trigger-${type}`): LoopTriggerDTOApi {
    return {
        id,
        loop_id: 'loop-1',
        type,
        enabled: true,
        config,
        schedule_sync_status: null,
        last_fired_at: null,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
    }
}

function loop(triggers: LoopTriggerDTOApi[]): LoopDTOApi {
    return {
        id: 'loop-1',
        team_id: 1,
        created_by_id: 1,
        name: 'Dependency check',
        description: '',
        visibility: 'team',
        instructions: 'Update outdated dependencies.',
        runtime_adapter: 'claude',
        model: '',
        reasoning_effort: null,
        repositories: [{ github_integration_id: 7, full_name: 'example/app' }],
        sandbox_environment_id: null,
        enabled: true,
        disabled_reason: null,
        overlap_policy: 'skip',
        behaviors: { create_prs: true, watch_ci: true, fix_review_comments: false, max_fix_iterations: 5 },
        connectors: {},
        notifications: { push: {}, email: {}, slack: {} },
        internal: false,
        origin_product: '',
        last_run_at: null,
        last_run_status: null,
        last_error: null,
        consecutive_failures: 0,
        created_at: '2026-01-01T00:00:00Z',
        updated_at: '2026-01-01T00:00:00Z',
        triggers,
        skill_bundles: [],
    }
}

const WEEKLY = trigger('schedule', { cron_expression: '30 9 * * 1', timezone: 'Europe/Prague' })
const GITHUB = trigger('github', { github_integration_id: 7, repository: 'example/app', events: ['issues'] })
const CUSTOM_CRON = trigger('schedule', { cron_expression: '*/15 * * * *', timezone: 'UTC' })

describe('loopForm', () => {
    test.each([
        ['a GitHub trigger', [GITHUB]],
        ['a custom cron schedule', [CUSTOM_CRON]],
        ['more than one trigger', [WEEKLY, GITHUB]],
        ['a weekly schedule', [WEEKLY]],
        ['no triggers', []],
    ])('renaming a loop with %s sends only the name', (_, triggers) => {
        const saved = loop(triggers)
        expect(loopPatch(saved, { ...loopToFormValues(saved), name: 'Renamed' })).toEqual({ name: 'Renamed' })
    })

    it('updates the edited schedule trigger in place', () => {
        const saved = loop([WEEKLY])
        const values = loopToFormValues(saved)
        expect(loopPatch(saved, { ...values, schedule: { ...values.schedule, time: '17:00' } })).toEqual({
            triggers: [
                {
                    id: WEEKLY.id,
                    type: 'schedule',
                    enabled: true,
                    config: { cron_expression: '0 17 * * 1', timezone: 'Europe/Prague' },
                },
            ],
        })
    })

    it('keeps behavior settings the form does not show when pull requests are turned off', () => {
        const saved = loop([WEEKLY])
        expect(loopPatch(saved, { ...loopToFormValues(saved), createPullRequests: false })).toEqual({
            behaviors: { create_prs: false, watch_ci: true, fix_review_comments: false, max_fix_iterations: 5 },
        })
    })

    test.each(['0 * * * *', '5 8 * * *', '30 9 * * 1-5', '0 18 * * 0'])('round-trips the cron %s', (cron) => {
        expect(compileCronSchedule(parseCronSchedule(cron)!)).toEqual(cron)
    })
})
