import type { ImpactLensType } from '../recommendations/types'

export interface ImpactLensInfo {
    label: string
    // What the lens flags, with the thresholds and time range it uses, so a reader can judge each item.
    description: string
    // What a project is missing when the lens cannot run, so the tab says what to send rather than only that it failed.
    unavailableReason: string
}

// Each description states the full rule and its thresholds, which match the constants in the backend lens modules
// under products/error_tracking/backend/logic/recommendations/. Change both together.
export const IMPACT_LENS_INFO: Record<ImpactLensType, ImpactLensInfo> = {
    flow_drop: {
        label: 'Broken flow',
        description:
            "Every hour, the pages people usually move between, such as login to home, are compared with the same hour on the previous 7 days. Up to 8 flows are watched, picked from the last day of pageviews: steps from one page to the next that 5% to 95% of a page's visitors take, and at least 40 sessions take. A visit gets through when it reaches the second page within 30 minutes. A flow is flagged when, with at least 200 visits, the share that gets through drops by at least 8 points and to below three quarters of usual. The usual rate needs at least 4 of the previous 7 days with 30 or more visits. Drops from extra traffic, with at least 3 times the usual visits and at least 0.9 times the usual finishes, are left out. An error is listed only when at least 20 visits got it on the first page in their first 10 seconds, those visits got through at most half as often as the other visits by at least 4 standard errors, and, when the error had at least 20 such visits at that hour on the previous days, that gap is at least 15 points wider than its usual gap there. Known harmless patterns and errors that fire as people leave are never listed. Flows come from pageviews, so they show broken page loads and navigation, not failing requests. Covers the 24 complete hours that end at least 90 minutes ago.",
        unavailableReason: 'Not enough traffic between pages',
    },
    funnel_step: {
        label: 'Broken funnel step',
        description:
            'The flows that Broken flow watches are linked into chains of 3 or 4 pages that people move through in order, such as home to a list to one item, without visiting a page twice. A visit gets through when it reaches each next page within 30 minutes of the page before. Every hour, the share of visits that get through the whole chain is compared with the same hour on the previous 7 days. A chain is flagged when, with at least 200 visits, that share falls below seven tenths of usual by at least 4 standard errors. The usual share needs at least 4 of the previous 7 days with 30 or more visits. Drops from extra traffic, with at least 3 times the usual visits and at least 0.9 times the usual finishes, are left out, and so are chains that dropped more than 3 times in the last 21 days. The broken step is the one furthest below its own usual rate, among steps that at least 30 visits entered. It is clear when it fell below three quarters of usual and every other step stayed at 0.9 times usual or better. An error is listed when it passes the same test as in Broken flow, on the first page of the broken step. Known harmless patterns and errors that fire as people leave are never listed. Covers the 24 complete hours that end at least 90 minutes ago.',
        unavailableReason: 'Not enough traffic through 3 or more pages in a row',
    },
    quick_leave: {
        label: 'Page fails to load',
        description:
            'The error fires in the first 3 seconds of a page, and people leave that page between 3 and 13 seconds after it opened at least 1.5 times as often as people with the same browser, device and kind of visitor on the same page without an error, by at least 4 standard errors. It needs at least 50 such pageviews, and each page and kind of visitor needs at least 30 pageviews without an error to compare with. Fake errors on random pageviews check the comparison and raise the bar when they show an effect. This usually means the page did not load properly. Errors that fire because people leave are left out. An issue is flagged only when this holds on two days a week apart, the most recent ending a day ago. The return rate shows how many of the people who left came back within a day. Issues that are likely noise are left out, see Hidden as noise.',
        unavailableReason: 'Not enough page duration data',
    },
    lost_visitor: {
        label: 'Lost visitors',
        description:
            'The error fires in the first 3 seconds of a page, and the visit ends on that page with no new visit by the same person within a day, at least 1.5 times as often as for visitors with the same browser, device and kind of visitor on the same page without an error, by at least 4 standard errors. It needs at least 50 such pageviews, and each page and kind of visitor needs at least 30 pageviews without an error to compare with. Fake errors on random pageviews check the comparison and raise the bar when they show an effect. Errors that fire because people leave are left out. An issue is flagged only when this holds on two days a week apart, the most recent ending a day ago. Issues that are likely noise are left out, see Hidden as noise.',
        unavailableReason: 'Not enough pageviews to compare',
    },
    suppressed_events: {
        label: 'Stops next steps',
        description:
            'The 10 issues with the most sessions are checked, each on the page where it most often fires within 10 seconds of loading, with at least 60 such sessions and at least 200 sessions on the same page without it. The lens lists events that at least 3% of sessions send in the next 10 minutes, but at most half as often after the error, by at least 5 standard errors. Up to 3 events per issue. Errors that fire because people leave are left out. The lens does not know what an event means, so check that the events matter to you. Last 24 hours. Issues that are likely noise are left out, see Hidden as noise.',
        unavailableReason: 'No custom events after errors',
    },
    support_tickets: {
        label: 'Support tickets',
        description:
            'People opened a support ticket from the widget within 5 minutes after the error, at least 3 times as often per session as your usual rate of tickets, with at least 2 tickets. Uses up to 5,000 of the most recent widget tickets with a session from the last 30 days. Issues that are likely noise are left out, see Hidden as noise.',
        unavailableReason: 'No support tickets with a session',
    },
    many_accounts: {
        label: 'Many accounts',
        description:
            'The issue reached at least 10 accounts and at least 5% of your active accounts in the last 14 days, so it is a general problem rather than one customer’s. Active accounts are the accounts seen on pageviews or exceptions. Issues that are likely noise are left out, see Hidden as noise.',
        unavailableReason: 'No accounts on pageviews or exceptions',
    },
    one_account: {
        label: 'One account',
        description:
            'One account has at least half of the issue’s sessions in the last 14 days, with at least 20 sessions, so it is likely one customer’s setup or data. Issues that are likely noise are left out, see Hidden as noise.',
        unavailableReason: 'No accounts on events',
    },
    audience_slices: {
        label: 'One audience',
        description:
            'At least 30% of the issue’s sessions come from one browser, browser version, operating system, device type or kind of visitor (bot, in-app browser or webview), and that slice is at least 3 times as common as in your web pageview traffic, by at least 6 standard errors. It needs at least 60 sessions with the issue, at least half of them with a pageview, and at least 100 pageview sessions. Last 24 hours. Issues that are likely noise are left out, see Hidden as noise.',
        unavailableReason: 'Fewer than 100 pageview sessions',
    },
    related_issues: {
        label: 'Related issue',
        description:
            'Two issues first fire within 5 seconds of each other in at least 15 sessions, and those sessions are at least half of the sessions with either issue. When most of those sessions have one issue strictly first, and the same issue is first in at least 90% of them, it likely leads to the other. When each issue shares at least 95% of its sessions with the other, they are likely one problem filed twice. Last 24 hours. Issues that are likely noise are left out, see Hidden as noise.',
        unavailableReason: 'No issue reached 15 sessions',
    },
    fires_on_leave: {
        label: 'Fires as people leave',
        description:
            'The issue’s first occurrence in a session lands between 1 second before and 2 seconds after a page close at least twice as often as a random click or pageview does, and in at least 10% of its sessions. It needs at least 40 sessions. Leaving the page causes these errors, so they are left out of Page fails to load, Lost visitors, Stops next steps, and the errors listed for a Broken flow. Last 24 hours.',
        unavailableReason: 'No pageleave events',
    },
    inflated_counts: {
        label: 'Repeats in a loop',
        description:
            'A few sessions produce a large share of the issue’s events: one session has at least 20% of them, sessions with 50 or more events have at least 30% of them, or at least 10 sessions repeat it 5 or more times and a fifth of those repeat it on a steady timer. A steady timer means at least 60% of the gaps between its events are within a tenth of their median gap, and that gap is at least 1 second. The event count makes the issue look bigger than it is. It needs at least 40 sessions. Last 24 hours.',
        unavailableReason: 'No issue reached 40 sessions',
    },
    known_patterns: {
        label: 'Hidden as noise',
        description:
            'Issues that are likely noise, which the other lenses leave out, except Broken flow and Broken funnel step: during a broken deploy, failed loads and requests are the clue. An issue is likely noise when its most common web error message matches a pattern that is usually noise or outside your control, such as a ResizeObserver loop, a cross-origin script error, a browser extension, a chunk or hydration failure, an aborted or failed request, an HTTP error status, a non-error rejection, or a webview or link scanner error. A message shaped like a code bug, such as one that reads a property of undefined, never counts as a noise pattern. An issue is also likely noise when, in at least half of its events, the innermost frame is in a script on another domain that your source maps don’t resolve, the stack has no frame in your own code, or your app caught the error and reported it as a plain Error with a sentence for a message, such as “Not found.”. Issues are judged on the last day, or on the week before it when they had no errors that day. The list shows issues with at least 20 events in the last 24 hours.',
        unavailableReason: 'No web exceptions',
    },
}
