import type {
    SignalScoutCreateApi,
    SignalScoutSlackDestinationApi,
} from 'products/signals/frontend/generated/api.schemas'
import {
    DEFAULT_SCOUT_WEEKLY_DAY,
    MAX_SCOUT_DISPLAY_NAME_LENGTH,
    dayTimeToWeeklyCron,
    timeToDailyCron,
} from 'products/signals/frontend/inbox/utils/scoutRunsWindow'

import dashboardScoutSkill from './dashboardScoutSkill.md?raw'

export type DashboardScoutCadence = 'weekdays' | 'daily' | 'weekly'
export type DashboardScoutPostMode = 'on_change' | 'every_run' | 'custom'

export interface DashboardScoutSetup {
    destination: SignalScoutSlackDestinationApi | null
    cadence: DashboardScoutCadence
    time: string
    postMode: DashboardScoutPostMode
    /** When to post, in the person's own words. Read only when `postMode` is `custom`. */
    postPrompt: string
    focus: string
}

export const DASHBOARD_SCOUT_CADENCE_OPTIONS: { value: DashboardScoutCadence; label: string }[] = [
    { value: 'weekdays', label: 'Every weekday' },
    { value: 'daily', label: 'Every day' },
    { value: 'weekly', label: 'Every Monday' },
]

export const DASHBOARD_SCOUT_TIME_OPTIONS: { value: string; label: string }[] = Array.from(
    { length: 24 },
    (_, hour) => {
        const time = `${String(hour).padStart(2, '0')}:00`
        return { value: time, label: time }
    }
)

export const DEFAULT_DASHBOARD_SCOUT_SETUP: DashboardScoutSetup = {
    destination: null,
    cadence: 'weekdays',
    time: '09:00',
    postMode: 'on_change',
    postPrompt: '',
    focus: '',
}

const POST_MODE_INSTRUCTIONS: Record<Exclude<DashboardScoutPostMode, 'custom'>, string> = {
    every_run:
        'Post an update on every run. When something moved, lead with that. On a quiet run, file one short report that says the dashboard is in its normal range and how many insights you checked, with no detail section.',
    on_change:
        'Post only when an insight moved away from its own baseline or a tile is broken. A run where every tile sits inside its baseline ends with no report, and that is a good outcome.',
}

export function hasSlackTarget(destination: SignalScoutSlackDestinationApi | null): boolean {
    return !!destination && (!!destination.channel || !!destination.users?.length)
}

const NO_FOCUS_INSTRUCTIONS =
    'Treat every insight on the dashboard as equally important until a scout note says otherwise.'

/**
 * The tag that ties a scout to the dashboard it was set up from. A scout config has no dashboard
 * field, so the subscriptions modal finds a dashboard's scouts by this tag.
 */
export function dashboardScoutTag(dashboardId: number): string {
    return `dashboard-${dashboardId}`
}

export function dashboardScoutCron(cadence: DashboardScoutCadence, time: string): string {
    if (cadence === 'weekly') {
        return dayTimeToWeeklyCron(DEFAULT_SCOUT_WEEKLY_DAY, time)
    }
    const daily = timeToDailyCron(time)
    return cadence === 'weekdays' ? daily.replace(/\*$/, '1-5') : daily
}

function quoted(intro: string, text: string): string | null {
    const lines = text
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
    return lines.length === 0 ? null : [intro, ''].concat(lines.map((line) => `> ${line}`)).join('\n')
}

function focusInstructions(focus: string): string {
    return (
        quoted('The person who set you up said this about what matters on the dashboard:', focus) ??
        NO_FOCUS_INSTRUCTIONS
    )
}

function postModeInstructions({ postMode, postPrompt }: Pick<DashboardScoutSetup, 'postMode' | 'postPrompt'>): string {
    if (postMode !== 'custom') {
        return POST_MODE_INSTRUCTIONS[postMode]
    }
    return (
        quoted('The person who set you up described when to post like this:', postPrompt) ??
        POST_MODE_INSTRUCTIONS.on_change
    )
}

function dashboardScoutSubjectName(dashboardId: number, dashboardName: string): string {
    return dashboardName.trim() || `Dashboard ${dashboardId}`
}

export function renderDashboardScoutBody(
    dashboardId: number,
    dashboardName: string,
    setup: Pick<DashboardScoutSetup, 'postMode' | 'postPrompt' | 'focus'>
): string {
    const values: Record<string, string> = {
        dashboard_id: String(dashboardId),
        dashboard_name: dashboardScoutSubjectName(dashboardId, dashboardName),
        post_mode: postModeInstructions(setup),
        focus: focusInstructions(setup.focus),
    }
    // One pass over the template, so a `{{ ... }}` typed into the focus box or a dashboard name
    // stays literal text and is not expanded a second time.
    return dashboardScoutSkill.replace(/\{\{ (\w+) \}\}/g, (placeholder, key: string) => values[key] ?? placeholder)
}

export function buildDashboardScoutPayload(
    dashboardId: number,
    dashboardName: string,
    setup: DashboardScoutSetup & { destination: SignalScoutSlackDestinationApi }
): SignalScoutCreateApi {
    const name = dashboardScoutSubjectName(dashboardId, dashboardName)
    return {
        display_name: `${name} scout`.slice(0, MAX_SCOUT_DISPLAY_NAME_LENGTH),
        description: `Watches the "${name}" dashboard and posts what changed in Slack.`,
        body: renderDashboardScoutBody(dashboardId, name, setup),
        config: {
            run_cron_schedule: dashboardScoutCron(setup.cadence, setup.time),
            output_destinations: { slack: setup.destination },
            tags: ['dashboards', dashboardScoutTag(dashboardId)],
            // A scout that does not post on every run is valuable when it stays silent, which the
            // inactivity sweep would read as dead.
            ...(setup.postMode === 'every_run' ? {} : { auto_pause_exempt: true }),
        },
    }
}
