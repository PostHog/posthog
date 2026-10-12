import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { InsightDataCheckApi } from 'products/product_analytics/frontend/generated/api.schemas'

export interface DataCheckPromptContext {
    insightUrl: string | null
    /** The events the insight reads, or 'all' when a series reads every event. */
    events: string[] | 'all'
    eventsChecked: number
    /** The checks read a sample of the insight's events and not every one. */
    sampled: boolean
}

const MAX_EVENT_NAMES = 10
const MAX_EVENT_NAME_LENGTH = 80

// A name is whatever an SDK or a person sent, so it must not be able to add lines of its own to a prompt.
function quotedOneLine(text: string): string {
    const oneLine = Array.from(text, (character) => (character < ' ' || character === '\u007f' ? ' ' : character))
        .join('')
        .trim()
    return JSON.stringify(oneLine.slice(0, MAX_EVENT_NAME_LENGTH))
}

function eventsLine(events: string[] | 'all'): string {
    if (events === 'all') {
        return 'every event in the project'
    }
    const names = events
        .slice(0, MAX_EVENT_NAMES)
        .map((name) => quotedOneLine(name))
        .join(', ')
    return events.length > MAX_EVENT_NAMES ? `${names} and ${events.length - MAX_EVENT_NAMES} more` : names
}

function fixSteps(check: InsightDataCheckApi): string {
    switch (check.key) {
        case 'internal_users':
            return check.action === 'filter_internal_users'
                ? 'Turn on the internal and test users filter for this insight. In the insight query that is `filterTestAccounts: true`.'
                : "This project has no internal and test users filter, so PostHog cannot tell our own team's activity from real usage. Work out how to recognize our team, for example by an email domain, an internal IP range or a person property. Then set up the filter in the project settings and turn it on for this insight."
        case 'local_development':
            return 'Events from local development reach this project. The better fix is in the code: find where the app starts PostHog, and stop local builds from sending to this project, for example with a separate project for development. If that cannot be done, add a rule that excludes localhost hosts to the internal and test users filter, and turn that filter on for this insight.'
        case 'bot_traffic':
            return 'Add the rule "Traffic type is not Bot or AI Agent" to the internal and test users filter of the project, and turn that filter on for this insight.'
        case 'duplicate_events':
            return 'One person sent the same event from the same page twice in one second. First find which events and pages this happens on. Then find the cause in the code. The usual causes are PostHog starting more than once, and one event sent from two places, such as a handler bound twice or both the client and the server sending it. Change the code so each event is sent once.'
    }
}

export function dataCheckFixPrompt(check: InsightDataCheckApi, context: DataCheckPromptContext): string {
    return [
        'A data check on a PostHog insight found something that makes its numbers less reliable. Please fix it.',
        '',
        `Insight: ${context.insightUrl ?? 'not saved yet, so it has no link'}`,
        `Events the insight reads: ${eventsLine(context.events)}`,
        `Check: ${check.name}`,
        `Result: ${check.result}. The check read ${context.sampled ? 'a sample of ' : ''}${humanFriendlyNumber(context.eventsChecked)} events.`,
        '',
        'What to do:',
        fixSteps(check),
        '',
        'If you can change PostHog, for example through the PostHog MCP server, make the change there. If you cannot, give me the exact steps. Then tell me how to confirm the numbers are right.',
    ].join('\n')
}
