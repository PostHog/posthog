import type { TurnSuggestion } from '../types/streamTypes'

export const BASE = {
    turnIndex: 0,
    intent: 'metric_state',
    confidence: 0.9,
    title: 'Get this in Slack every week',
    description: 'A scout runs this analysis again every week and posts the results to Slack.',
}

export const SCOUT = {
    mode: 'report',
    displayName: 'Weekly signups',
    description: 'Counts signed_up events for the last 7 days.',
    body: '# Weekly signups\n\nQuery signed_up for the last 7 days.',
    cadence: 'weekly',
}

export const INSIGHT = { insightShortId: 'abc123', insightId: 42, insightName: 'Signups' }

export const INCIDENT_NOTEBOOK = {
    title: 'Why signups dropped on Tuesday',
    summary: 'A checkout error was the cause.',
    incident: { timeline: '- 14:10 release', cause: 'Checkout error.', fix: 'Rolled back.' },
}

export const SUGGESTION_FRAMES: Record<TurnSuggestion['kind'], Record<string, unknown>> = {
    scout: { ...BASE, kind: 'scout', scout: SCOUT },
    notebook: { ...BASE, kind: 'notebook', notebook: INCIDENT_NOTEBOOK },
    alert: { ...BASE, kind: 'alert', alert: { ...INSIGHT, direction: 'decrease', changePercent: 20.4 } },
    subscription: { ...BASE, kind: 'subscription', subscription: { ...INSIGHT, cadence: 'weekly' } },
    error_alert: { ...BASE, kind: 'error_alert', errorAlert: { issueId: 'issue-1', issueName: 'Checkout error' } },
}
