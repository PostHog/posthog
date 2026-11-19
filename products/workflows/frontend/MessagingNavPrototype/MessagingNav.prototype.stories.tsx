// PROTOTYPE, never merged: PostHog/michaelr-context#419. Round 1: three ways into Email & Messaging, in the
// today-rail-nav shell. Open a story, then flip variants with the bar at the bottom or the arrow keys.
import type { Meta, StoryObj } from '@storybook/react'

import { FEATURE_FLAGS } from 'lib/constants'
import { App } from 'scenes/App'

import {
    MessagingNavVariant,
    messagingNavPrototypeLogic,
} from '~/layout/today/messagingNavPrototype/messagingNavPrototypeLogic'
import { MessagingNavPrototypeSwitcher } from '~/layout/today/messagingNavPrototype/MessagingNavPrototypeSwitcher'
import { mswDecorator } from '~/mocks/browser'

import { SendCalendar } from '../SendCalendar/SendCalendar'
import { registerPrototypeCalendar } from './MessagingHomePrototypeSections'
import { PROTOTYPE_WORKFLOWS } from './prototypeData'

const ACTION_TYPES: Record<string, string> = {
    Email: 'function_email',
    SMS: 'function_sms',
    Push: 'function_push',
    Slack: 'function',
    Webhook: 'function',
    'Update person': 'function',
}

const HOG_FLOWS = PROTOTYPE_WORKFLOWS.map((w, index) => ({
    id: `0190f0f0-0000-7000-8000-00000000000${index}`,
    name: w.name,
    description: '',
    version: 1,
    status: w.status === 'Live' ? 'active' : w.status === 'Draft' ? 'draft' : 'archived',
    origin_product: w.kind === 'Loop' ? 'loops' : null,
    trigger: { type: 'event', filters: {} },
    actions: [
        { id: 'trigger_node', type: 'trigger', name: 'Trigger', config: { type: 'event', filters: {} } },
        ...w.channels.map((channel, i) => ({
            id: `action_${i}`,
            type: ACTION_TYPES[channel],
            name: channel,
            config: { template_id: `template-${channel.toLowerCase().replace(' ', '-')}`, inputs: {} },
        })),
        { id: 'exit_node', type: 'exit', name: 'Exit', config: { reason: 'Default exit' } },
    ],
    edges: [],
    tags: [],
    created_by: { id: 1, uuid: 'user-1', first_name: 'Alex', email: 'alex@example.com' },
    created_at: '2026-10-01T09:00:00Z',
    updated_at: '2026-11-10T09:00:00Z',
    user_access_level: 'editor',
    kind: w.kind,
}))

function hogFlowsFor(url: URL): { count: number; results: typeof HOG_FLOWS } {
    const types = (url.searchParams.get('type') ?? '').split(',').filter(Boolean)
    const results = types.length
        ? HOG_FLOWS.filter((flow) => types.includes(flow.kind.toLowerCase()))
        : HOG_FLOWS.filter((flow) => flow.status !== 'archived')
    return { count: results.length, results }
}

// The calendar row shows the shipped send calendar, so it gets a few invented sends around the story's date.
const calendarFlow = (
    n: number,
    name: string,
    broadcast: boolean,
    rrule: string,
    startsAt: string,
    cohortId: number
): Record<string, unknown> => ({
    id: `0190f0f0-0000-7000-8000-0000000001${n}`,
    name,
    origin_product: broadcast ? 'broadcasts' : null,
    created_by: { id: 1, uuid: 'user-1', first_name: 'Alex', email: 'alex@example.com' },
    user_access_level: 'editor',
    trigger_type: 'batch',
    audience_properties: [{ key: 'id', type: 'cohort', value: cohortId }],
    audience_type: null,
    email_to: null,
    message_category_id: null,
    schedules: [
        {
            id: `0190f0f0-0000-7000-8000-0000000002${n}`,
            rrule,
            starts_at: startsAt,
            timezone: 'UTC',
            status: 'active',
            next_run_at: null,
            created_at: '2026-11-01T09:00:00Z',
            updated_at: '2026-11-01T09:00:00Z',
        },
    ],
    batch_jobs: [],
})

const CALENDAR_FLOWS = [
    calendarFlow(1, 'November product update', true, 'FREQ=DAILY;COUNT=1', '2026-11-21T10:00:00Z', 31),
    calendarFlow(2, 'Webinar reminder: data pipelines', true, 'FREQ=DAILY;COUNT=1', '2026-11-25T15:00:00Z', 32),
    calendarFlow(3, 'Weekly digest', false, 'FREQ=WEEKLY;BYDAY=TU', '2026-10-06T09:00:00Z', 33),
    calendarFlow(4, 'Monthly tips', false, 'FREQ=MONTHLY;BYMONTHDAY=3', '2026-10-03T08:00:00Z', 33),
]

const COHORTS = [
    { id: 31, name: 'All active users', count: 4200 },
    { id: 32, name: 'Webinar sign-ups', count: 310 },
    { id: 33, name: 'Newsletter subscribers', count: 1800 },
].map((c) => ({ ...c, is_static: false, is_calculating: false, deleted: false, filters: {}, groups: [] }))

registerPrototypeCalendar(SendCalendar)

let appliedForStory: string | null = null

const meta: Meta = {
    component: App,
    title: 'Prototypes/Email & Messaging navigation',
    decorators: [
        mswDecorator({
            get: {
                '/api/projects/:team_id/hog_flows/': ({ request }) => hogFlowsFor(new URL(request.url)),
                '/api/projects/:team_id/hog_flows/email_sending_suspension/': { suspended: false },
                '/api/projects/:team_id/hog_flow_templates/': { count: 0, results: [] },
                '/api/projects/:team_id/messaging_categories/': { count: 0, results: [] },
                '/api/projects/:team_id/messaging_templates/': { count: 0, results: [] },
                '/api/projects/:team_id/health_issues/summary/': {},
                '/api/projects/:team_id/hog_flows/send_calendar/': CALENDAR_FLOWS,
                '/api/projects/:team_id/cohorts/': { count: COHORTS.length, results: COHORTS },
                '/api/projects/:team_id/cohorts/:id/': ({ params }) => COHORTS.find((c) => String(c.id) === params.id),
            },
            post: {
                '/api/projects/:team_id/file_system/home_folder/': { id: 'home-folder', path: 'Users/Alex Example' },
            },
        }),
        (Story, { id, parameters }) => {
            // The shell reads the variant while it maps the first URL to a pane, so it is set before the first render.
            // Once per story, so a later render never undoes a switch made with the bar.
            messagingNavPrototypeLogic.mount()
            if (appliedForStory !== id) {
                appliedForStory = id
                messagingNavPrototypeLogic.actions.setVariant(parameters.variant as MessagingNavVariant)
            }
            return (
                <>
                    <Story />
                    <MessagingNavPrototypeSwitcher />
                </>
            )
        },
    ],
    parameters: {
        layout: 'fullscreen',
        viewMode: 'story',
        mockDate: '2026-11-19 10:00:00',
        featureFlags: [FEATURE_FLAGS.TODAY_RAIL_NAV, FEATURE_FLAGS.WORKFLOWS_TRANSACTIONAL_EMAIL_API],
    },
}
export default meta

type Story = StoryObj

export const VariantA: Story = {
    parameters: { variant: 'A', pageUrl: '/messaging/broadcasts?variant=A' },
}
export const VariantB: Story = {
    parameters: { variant: 'B', pageUrl: '/messaging/broadcasts?variant=B' },
}
export const VariantC: Story = {
    parameters: { variant: 'C', pageUrl: '/messaging/broadcasts?variant=C' },
}
export const CalendarRow: Story = {
    parameters: { variant: 'B', pageUrl: '/messaging/calendar?variant=B' },
}
export const WorkflowsAfterTheMove: Story = {
    parameters: { variant: 'B', pageUrl: '/workflows?variant=B' },
}
