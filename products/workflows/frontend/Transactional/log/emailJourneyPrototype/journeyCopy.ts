// PROTOTYPE (ticket #385), throwaway. Copy for the cases every variant has to explain.
import type { JourneyClick, JourneyData, JourneyLink, JourneySession } from './journeyFixtures'

export function noSessionText(click: JourneyClick, link: JourneyLink, data: JourneyData): string {
    if (click.noSession === 'off-domain') {
        return `This link goes to ${new URL(link.url).hostname}, outside ${data.sendingDomain.replace(/^mail\./, '')}, so PostHog can't follow it to a session.`
    }
    return "PostHog saw the click, but no visit with this email's link tag reached your product. Check that your site runs PostHog and keeps the URL's query string."
}

export function whoText(session: JourneySession, data: JourneyData): string | null {
    if (session.who === 'someone-else') {
        return `Not identified as ${data.person?.name.split(' ')[0] ?? 'the recipient'}. The email may have been forwarded, or they used a browser where they aren't logged in.`
    }
    if (session.who === 'unlinked') {
        return 'Matched by the link, not by a person.'
    }
    return null
}

export const NOT_TRACKED_TEXT =
    "Opens and link clicks aren't tracked for this email, so there's nothing to follow into your product. Turn on Track opens and link clicks for the email, or check whether it's marked sensitive."

export const NO_CLICKS_TEXT =
    'No clicks yet. When the recipient clicks a link, the click and the session it started show up here.'

export const NO_PERSON_TEXT =
    "This send named no distinct_id, so it isn't linked to a person. Sessions still show when a link click leads to one. Pass distinct_id when you send to see the person too."

export const EVENTS_OFF_TEXT =
    "Engagement events are off, so these opens and clicks don't appear in the person's events or in insights. This page doesn't need them."

export const NO_RECORDING_TEXT = 'No recording. Session replay is off for this project.'
