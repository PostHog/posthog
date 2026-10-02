import {
    type LoopFormValues,
    type LoopTriggerDraft,
    defaultLoopContextOutputs,
    emptyLoopFormValues,
    formValuesToLoopWrite,
    loopFormInvalidReason,
} from './loopFormValues'
import { hogFlowScheduleToScheduleConfig, scheduleConfigToHogFlowSchedule } from './loopSchedule'
import { formValuesToHogFlowWrite, hogFlowToFormValues, isLoopShapedHogFlow } from './loopWorkflowMapping'

const TZ = 'America/Los_Angeles'
// A Friday, 18:00 in Los Angeles.
const NOW = new Date('2026-10-03T01:00:00Z')

function scheduleTrigger(cron: string): LoopTriggerDraft {
    return { key: 't', type: 'schedule', enabled: true, config: { cron_expression: cron, timezone: TZ } }
}

function values(extra: Partial<LoopFormValues> = {}): LoopFormValues {
    return {
        ...emptyLoopFormValues(),
        name: 'Digest',
        instructions: 'Summarize the week.',
        visibility: 'team',
        triggers: [scheduleTrigger('0 9 * * 1-5')],
        contextTarget: { spaceId: 'space-a', name: 'checkout', outputs: defaultLoopContextOutputs() },
        ...extra,
    }
}

describe('loop form', () => {
    it.each([
        ['every hour', '0 * * * *', 'FREQ=HOURLY;INTERVAL=1', '2026-10-03T02:00:00.000Z'],
        ['every day', '30 8 * * *', 'FREQ=DAILY;INTERVAL=1', '2026-10-03T15:30:00.000Z'],
        [
            'weekdays, skipping the weekend',
            '0 9 * * 1-5',
            'FREQ=WEEKLY;INTERVAL=1;BYDAY=MO,TU,WE,TH,FR',
            '2026-10-05T16:00:00.000Z',
        ],
        ['one day a week', '15 7 * * 3', 'FREQ=WEEKLY;INTERVAL=1;BYDAY=WE', '2026-10-07T14:15:00.000Z'],
    ])('keeps %s the same through a workflow schedule row', (_, cron, rrule, startsAt) => {
        const row = scheduleConfigToHogFlowSchedule({ cron_expression: cron, timezone: TZ }, NOW)
        expect(row).toEqual({ rrule, starts_at: startsAt, timezone: TZ })
        expect(hogFlowScheduleToScheduleConfig(row!)).toEqual({ cron_expression: cron, timezone: TZ })
    })

    it.each([
        ['an interval', 'FREQ=DAILY;INTERVAL=2'],
        ['days of the month', 'FREQ=MONTHLY;BYMONTHDAY=15,30'],
        ['an hourly rule off the hour', 'FREQ=HOURLY;INTERVAL=1'],
    ])('treats a rule with %s as one the form cannot edit', (_, rrule) => {
        expect(hogFlowScheduleToScheduleConfig({ rrule, starts_at: '2026-10-05T16:30:00Z', timezone: TZ })).toBeNull()
    })

    it('keeps workflow editor work when it saves an edit, and reads its own write back', () => {
        const existing = {
            id: 'flow-1',
            actions: [
                { id: 'trigger', name: 'When', type: 'trigger', config: { type: 'schedule' } },
                {
                    id: 'create_task',
                    name: 'Ask the agent',
                    type: 'function',
                    config: { template_id: 'template-posthog-create-task', inputs: { title: { value: 'Weekly' } } },
                },
                { id: 'notify', name: 'Tell Slack', type: 'function', config: { template_id: 'template-slack' } },
                { id: 'exit', name: 'Exit', type: 'exit', config: {} },
            ],
        }
        const form = values({
            repositories: [{ github_integration_id: 7, full_name: 'example/app' }],
            model: 'claude-sonnet-5',
            reasoningEffort: 'high',
            teamSkills: ['triage'],
        })
        const write = formValuesToHogFlowWrite(form, { enabled: true, existing })
        const task = write.flow.actions[1]

        expect(write.flow.actions.map((action) => action.name)).toEqual(['When', 'Ask the agent', 'Tell Slack', 'Exit'])
        expect(write.flow.edges.map((edge) => `${edge.from}>${edge.to}`)).toEqual([
            'trigger>create_task',
            'create_task>notify',
            'notify>exit',
        ])
        expect(task.config.inputs).toMatchObject({ title: { value: 'Weekly' }, channel: { value: 'space-a|checkout' } })

        const saved = {
            id: 'flow-1',
            actions: write.flow.actions,
            edges: write.flow.edges,
            schedules: [{ id: 's', ...write.schedule! }],
        }
        expect(isLoopShapedHogFlow(saved)).toBe(true)
        expect(hogFlowToFormValues(saved)).toMatchObject({
            instructions: form.instructions,
            repositories: [{ full_name: 'example/app' }],
            model: 'claude-sonnet-5',
            reasoningEffort: 'high',
            teamSkills: ['triage'],
            contextTarget: { spaceId: 'space-a', name: 'checkout' },
            triggers: [{ type: 'schedule', config: { cron_expression: '0 9 * * 1-5', timezone: TZ } }],
        })
    })

    it.each([
        ['staged edits', { draft: { actions: [] } }, []],
        [
            'a step the form did not add',
            {},
            [{ id: 'wait', name: 'Wait', type: 'function', config: { template_id: 'template-delay' } }],
        ],
    ])('marks a workflow with %s as changed outside the form', (_, extra, extraActions) => {
        const write = formValuesToHogFlowWrite(values(), { enabled: true })
        const flow = {
            id: 'flow-1',
            actions: [...write.flow.actions, ...extraActions],
            schedules: [{ id: 's', ...write.schedule! }],
            ...extra,
        }
        expect(isLoopShapedHogFlow(flow)).toBe(false)
    })

    it('writes a kept skill as its invocation and keeps payload values whole', () => {
        const write = formValuesToLoopWrite(
            values({
                skill: { name: 'weekly-digest', source: 'user' },
                skillContext: ' Focus on billing. ',
                triggers: [
                    {
                        key: 'g',
                        type: 'github',
                        enabled: true,
                        config: {
                            github_integration_id: 7,
                            repository: 'example/app',
                            events: ['pull_request'],
                            filters: { payload: [{ path: ' pull_request.title ', equals: 'release, approved' }] },
                        },
                    },
                ],
            })
        )
        expect(write.instructions).toBe('/weekly-digest\n\nFocus on billing.')
        expect(write.triggers?.[0].config).toMatchObject({
            filters: { payload: [{ path: 'pull_request.title', equals: ['release, approved'] }] },
        })
    })

    it.each([
        ['a workflow loop with no trigger', 'workflow' as const, { triggers: [] }, 'Add one trigger.'],
        [
            'a workflow loop with an API trigger',
            'workflow' as const,
            { triggers: [{ key: 'a', type: 'api' as const, enabled: true, config: {} }] },
            'Finish each trigger, or remove the ones you do not need.',
        ],
        ['a loops API loop with no trigger', 'loops' as const, { triggers: [] }, null],
        [
            'a loop in a space that is personal',
            'loops' as const,
            { visibility: 'personal' as const },
            'A loop in a space must be visible to the team.',
        ],
    ])('checks %s', (_, backend, extra, reason) => {
        expect(loopFormInvalidReason(values(extra), backend)).toBe(reason)
    })
})
