import { DemoReportContent } from './types'

/**
 * Per-report content for the v2 report pages. Scenarios are modeled on the kinds
 * of issues the inbox finds in this codebase; every number and quote is invented.
 */

/** Hover labels for a trailing 24-hour window, oldest first. */
export function hourlyPointLabels(count: number): string[] {
    return Array.from({ length: count }, (_, index) => (index === count - 1 ? 'now' : `${count - 1 - index}h ago`))
}

const HOURLY_24 = hourlyPointLabels(24)
const HOURLY_X_LABELS = ['24h ago', '12h ago', 'now']

export const REPORT_CONTENT: Record<string, DemoReportContent> = {
    'RPT-1042': {
        observation: {
            label: 'People clicking a dead Create key button',
            unit: 'per hour',
            chart: {
                series: [
                    {
                        name: 'Dead clicks',
                        color: 'danger',
                        points: [
                            9, 8, 10, 9, 26, 31, 29, 34, 38, 36, 41, 44, 43, 48, 52, 50, 55, 58, 57, 61, 60, 63, 62, 64,
                        ],
                    },
                    {
                        name: 'Keys created',
                        color: 'muted',
                        dashed: true,
                        points: [
                            31, 33, 32, 30, 22, 20, 21, 18, 17, 18, 15, 16, 14, 13, 12, 13, 11, 10, 11, 9, 10, 8, 9, 8,
                        ],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per hour',
                baselineValue: 9,
                baselineLabel: 'baseline 9/hr',
                annotations: [
                    { index: 4, label: 'deploy f3a1c72', color: 'danger' },
                    { index: 19, label: 'detected', color: 'accent', labelAnchor: 'end' },
                ],
            },
            liveRange: [56, 70],
        },
        occurrences: {
            label: 'Dead clicks on Create key, hourly',
            values: [9, 8, 10, 9, 26, 31, 29, 34, 38, 36, 41, 44, 43, 48, 52, 50, 55, 58, 57, 61, 60, 63, 62, 64],
            alarmFromIndex: 4,
        },
        evidence: [
            {
                label: 'Autocapture',
                title: '3,912 dead clicks on the Create key button',
                detail: 'Median 3 clicks per person before giving up. Clicks cluster within 2 seconds of each other.',
                bars: {
                    values: [9, 8, 10, 9, 26, 31, 29, 34, 38, 41, 44, 48, 52, 55, 58, 61, 63, 64],
                    alarmFromIndex: 4,
                },
            },
            {
                label: 'Session replay',
                title: '182 replays show the same loop',
                detail: 'Fill the form, click Create key, nothing changes, click again, leave settings without a key.',
            },
            {
                label: 'Error tracking',
                title: '0 exceptions on the failing path',
                detail: 'The validation error is computed and thrown away before render, so nothing is captured.',
            },
            {
                label: 'Funnel',
                title: 'Key creation completion fell 71% to 34%',
                detail: 'Settings visit to key created, compared with the trailing 14-day baseline.',
            },
            {
                label: 'Support',
                title: '3 tickets describe the button doing nothing',
                detail: 'All three arrived after the deploy. None got a workaround.',
            },
            {
                label: 'Deploy diff',
                title: 'f3a1c72 reordered validation and render',
                detail: 'The error state is set after the early return added in the same commit, so it never reaches the form.',
            },
        ],
        timeline: [
            {
                label: 'Deploy reorders the key form validation',
                time: 'Aug 19 07:41',
                chip: 'f3a1c72',
                color: 'danger',
            },
            { label: 'First dead-click cluster on Create key', time: 'Aug 19 07:58', chip: '+17 min', color: 'muted' },
            { label: 'Dead clicks pass 4x baseline', time: 'Aug 19 19:00', chip: '4x', color: 'muted' },
            { label: 'Anomaly detected, case opened', time: 'Aug 20 06:32', chip: 'auto', color: 'muted' },
            { label: 'Report published', time: 'Aug 20 06:58', chip: '26 min', color: 'success' },
        ],
        verdictHeadline: 'The Create key button swallows its own validation error',
        problem: [
            'When the new API key form fails validation, the click handler returns early before the error state reaches the form. The button stays enabled, nothing renders, and there is no message, no disabled reason, and no path forward except retrying the same dead click.',
            'The failure began 17 minutes after deploy f3a1c72 on Aug 19, which reordered validation and render on the key creation form. People creating keys are usually mid-setup, wiring an SDK or a CI job, so a silent failure here stalls an integration, and it does so without leaving a single error event behind.',
        ],
        replayCaption: 'One of 182 matching replays: three clicks on Create key in 5 seconds, then the tab closes.',
        impactTiles: [
            { value: '1,410', label: 'people hit the dead button', note: 'in 28 hours' },
            { value: '3,912', label: 'dead clicks recorded', note: 'median 3 per person' },
            { value: '34%', label: 'key creation completion', note: 'was 71%' },
            { value: '0', label: 'errors captured', note: 'the failure is silent' },
        ],
        howWeKnow: [
            'The first dead-click cluster lands 17 minutes after deploy f3a1c72, and every affected session runs code from that deploy.',
            'The diff moves the early return above the line that stores the validation error, so the error state is computed and then discarded.',
            'All 182 matching replays show the same loop: submit, no visible change, retry. None shows an error message.',
            'Key creation completion fell from 71% to 34% in the same window, with no other change to the settings surface.',
        ],
        causeDiff: {
            title: 'The change that introduced it, in f3a1c72',
            snippet:
                '   const errors = validateKeyForm(values)\n+  if (Object.keys(errors).length > 0) {\n+      return\n+  }\n   setFormErrors(errors)\n   if (Object.keys(errors).length > 0) {\n       return\n   }',
        },
        fix: {
            summary:
                'Set the form errors before the early return so the existing error rendering works again, and give the Create key button a disabled reason while the request is in flight. Behind a flag so the rollout can halt itself if dead clicks do not fall.',
            flagKey: 'api-key-error-surfacing',
            branch: 'fix/rpt-1042-api-key-errors',
            prTitle: 'fix(settings): surface API key validation errors on Create key',
            generationSteps: [
                'Reading the key form logic and the f3a1c72 diff',
                'Moving setFormErrors above the early return',
                'Wiring the in-flight state into the button disabled reason',
                'Running the settings test suite, 96 passing',
                'Preparing the diff for review',
            ],
            agentPrompt:
                'Fix RPT-1042: the Create key form computes validation errors but returns before storing them, so the button silently does nothing. Restore the error rendering, add a disabled reason while the request is in flight, and gate the change behind api-key-error-surfacing.',
            changes: [
                {
                    file: 'apiKeyFormLogic.ts',
                    snippet:
                        '   const errors = validateKeyForm(values)\n-  if (Object.keys(errors).length > 0) {\n-      return\n-  }\n   setFormErrors(errors)\n   if (Object.keys(errors).length > 0) {\n       return\n   }',
                },
                {
                    file: 'ApiKeyForm.tsx',
                    snippet:
                        '   <LemonButton\n       type="primary"\n+      loading={keySubmitting}\n+      disabledReason={firstFormError ?? undefined}\n       onClick={submitKey}\n   >',
                    note: 'The button now says why it is blocked instead of staying silently clickable.',
                },
            ],
            monitoringCriteria: 'dead clicks back to baseline, completion above 65%',
        },
    },

    'RPT-1044': {
        observation: {
            label: 'Sessions bouncing out of the scanner setup wizard',
            unit: 'per hour',
            chart: {
                series: [
                    {
                        name: 'Wizard bounces',
                        color: 'danger',
                        points: [
                            11, 13, 12, 14, 13, 15, 16, 15, 17, 18, 17, 19, 21, 20, 22, 23, 22, 24, 25, 24, 26, 27, 26,
                            28,
                        ],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per hour',
                annotations: [{ index: 20, label: 'investigating', color: 'accent', labelAnchor: 'end' }],
            },
            liveRange: [24, 32],
        },
        evidence: [
            {
                label: 'Paths',
                title: '41% of wizard entries return straight to the list',
                detail: 'Some of this is legitimate back navigation, so the figure is an upper bound.',
            },
            {
                label: 'Session replay',
                title: 'Replays show the template click landing back on the picker',
                detail: 'The chosen template is in the URL, but the configure step complains there is no scanner type.',
            },
            {
                label: 'Error tracking',
                title: 'AbortError spikes on the wizard routes',
                detail: 'The shape of an in-flight request torn down by a surprise navigation.',
            },
        ],
        timeline: [
            {
                label: 'Bounce rate first crosses alerting threshold',
                time: 'Aug 18 16:00',
                chip: '41%',
                color: 'danger',
            },
            { label: 'Anomaly detected, case opened', time: 'Aug 20 09:48', chip: 'auto', color: 'muted' },
            { label: 'Investigation running', time: 'now', chip: 'live', color: 'success' },
        ],
        verdictHeadline: 'Something keeps navigating people out of the scanner wizard',
        problem: [
            'People creating their first scanner pick a template, land in the setup wizard, and get bounced back to the scanner list with no error. The replace-style navigation leaves no history entry, so from the inside it looks like the wizard simply refused.',
            'The leading suspect is a stale list-page URL write racing the wizard navigation, but the investigation is still confirming which write wins and why the chosen template is dropped on arrival.',
        ],
        impactTiles: [
            { value: '41%', label: 'of wizard entries bounce', note: 'upper bound, last 7 days' },
            { value: '1,904', label: 'sessions affected', note: 'last 7 days' },
            { value: '2', label: 'suspect code paths', note: 'being narrowed now' },
        ],
        howWeKnow: [
            'Bounces from the details step were zero before the Aug 14 wizard rework and jumped the day it shipped.',
            'Replays show the template parameter still in the URL while the configure step reports no scanner type.',
            'AbortError and failed-fetch events cluster on exactly the wizard routes and nowhere else.',
        ],
    },

    'RPT-1039': {
        observation: {
            label: 'Clicks on the unclickable usage limit banner',
            unit: 'per hour',
            chart: {
                series: [
                    {
                        name: 'Dead clicks on banner text',
                        color: 'danger',
                        points: [4, 5, 4, 6, 5, 7, 6, 8, 7, 8, 9, 8, 10, 9, 11, 10, 12, 11, 12, 13, 12, 14, 13, 14],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per hour',
                annotations: [{ index: 16, label: 'detected', color: 'accent', labelAnchor: 'end' }],
            },
            liveRange: [11, 17],
        },
        screenshot: {
            kind: 'usage-banner',
            urlHint: 'us.posthog.com/organization/billing',
            source: 'from session replay 0190-77c4',
        },
        evidence: [
            {
                label: 'Autocapture',
                title: '1,900 dead clicks on the banner sentence in 30 days',
                detail: 'People click the words describing the action because nothing else on the banner is clickable.',
            },
            {
                label: 'Segment',
                title: 'Non-admins get no button at all',
                detail: 'The action ternary falls through to nothing when the viewer cannot access billing.',
            },
            {
                label: 'Support',
                title: '4 tickets from people stuck at their limit',
                detail: 'Two of them are from admins of orgs where data loss had already started.',
            },
        ],
        timeline: [
            { label: 'Banner copy tells people to upgrade', time: 'long-standing', chip: 'copy', color: 'muted' },
            {
                label: 'Dead-click pattern isolated to the banner text',
                time: 'Aug 18 10:40',
                chip: 'auto',
                color: 'muted',
            },
            { label: 'Report published', time: 'Aug 18 11:05', chip: '25 min', color: 'success' },
        ],
        verdictHeadline: 'The usage limit banner asks for an action it does not offer',
        problem: [
            'When an org hits a usage limit, the banner says to upgrade the plan or raise the billing limit, and then renders that sentence as plain text. Admins get a separate button beside it; non-admins get nothing clickable anywhere on the banner.',
            'These are people trying to pay us or stop losing data, at the exact moment the product asks them to act. They do the obvious thing and click the instruction itself, about 63 times a day.',
        ],
        impactTiles: [
            { value: '1,900', label: 'dead clicks in 30 days', note: 'on the banner sentence' },
            { value: '612', label: 'people affected', note: '30 days' },
            { value: '0', label: 'actions offered to non-admins', note: 'no button renders for them' },
        ],
        howWeKnow: [
            'Autocapture puts the dead clicks on the exact text nodes of the banner sentence, split across the admin and non-admin variants.',
            'The banner builder renders the message with no link in the body, and its action falls through to nothing without billing access.',
            'Ticket timestamps line up with limit-hit events for the same orgs.',
        ],
        fix: {
            summary:
                'Link the action phrase to the billing page for anyone with access, and give non-admins a one-click way to notify an org admin instead of a sentence about a page they cannot open.',
            flagKey: 'usage-banner-actionable',
            branch: 'fix/rpt-1039-usage-banner-link',
            prTitle: 'fix(billing): make the usage limit banner actionable for every viewer',
            generationSteps: [
                'Reading the project notice builder and both banner variants',
                'Linking the action phrase for viewers with billing access',
                'Adding the notify-an-admin action for everyone else',
                'Running the billing notice tests, 41 passing',
                'Preparing the diff for review',
            ],
            agentPrompt:
                'Fix RPT-1039: the usage limit banner renders its call to action as plain text and gives non-admins no control at all. Link the phrase to billing for viewers with access and add a notify-admin action for the rest, behind usage-banner-actionable.',
            changes: [
                {
                    file: 'projectNoticeLogic.tsx',
                    snippet:
                        "-  message: `${title}. ${message}`,\n+  message: (\n+      <>\n+          {title}.{' '}\n+          <Link to={canAccessBilling ? urls.organizationBilling() : undefined} onClick={notifyAdmin}>\n+              {message}\n+          </Link>\n+      </>\n+  ),",
                },
            ],
            monitoringCriteria: 'dead clicks on the banner near zero, limit-to-billing click-through up',
        },
    },

    'RPT-1037': {
        observation: {
            label: 'AI answers rendering an error where the chart should be',
            unit: 'per hour',
            chart: {
                series: [
                    {
                        name: 'Failed chart answers',
                        color: 'danger',
                        points: [2, 3, 2, 3, 4, 3, 4, 3, 4, 5, 4, 3, 4, 5, 4, 5, 4, 5, 4, 5, 5, 4, 5, 4],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per hour',
                baselineValue: 1,
                baselineLabel: 'expected ~1/hr',
            },
            liveRange: [3, 6],
        },
        screenshot: {
            kind: 'ai-error-card',
            urlHint: 'us.posthog.com/max',
            source: 'from session replay 018e-b511',
        },
        evidence: [
            {
                label: 'LLM traces',
                title: '97 traces end in a failed insight query',
                detail: 'The answer text is fine; the embedded query fails and the card renders the raw error.',
            },
            {
                label: 'Session replay',
                title: '41 replays show people rephrasing the same question',
                detail: 'The retry usually works, which means the failure was recoverable all along.',
            },
            {
                label: 'Query log',
                title: 'Most failures are timeouts or transient table locks',
                detail: 'The same query re-run within a minute succeeds in 9 of 10 cases.',
            },
        ],
        timeline: [
            { label: 'Failure rate settles at ~4x expected', time: 'Aug 15', chip: '4x', color: 'danger' },
            { label: 'Anomaly detected, case opened', time: 'Aug 17 14:55', chip: 'auto', color: 'muted' },
            { label: 'Report published', time: 'Aug 17 15:20', chip: '25 min', color: 'success' },
        ],
        verdictHeadline: 'AI chart answers give up on the first recoverable query error',
        problem: [
            'When someone asks PostHog AI for a chart and the insight query behind the answer fails, the answer renders a red error card in place of the visualization. There is no retry, even though the query log shows the same query succeeding on a re-run 9 times out of 10.',
            'People route around it by rephrasing the question, which re-runs the query and usually works. The product is making users do its retry loop by hand, about 184 times a week.',
        ],
        impactTiles: [
            { value: '184', label: 'people per week', note: 'see the error card' },
            { value: '9 of 10', label: 'failures recover on retry', note: 'from the query log' },
            { value: '0', label: 'automatic retries today', note: 'the card is a dead end' },
        ],
        howWeKnow: [
            'The 97 failing traces all fail in the query step, after the answer text streamed successfully.',
            'Re-running the identical failed queries succeeds in 9 of 10 cases within a minute.',
            'Replays show the rephrase-and-retry loop, which is a human doing what the client could do itself.',
        ],
        fix: {
            summary:
                'Retry recoverable query failures once with backoff before rendering the error card, and put a Run again button on the card for the rest.',
            flagKey: 'ai-answer-query-retry',
            branch: 'fix/rpt-1037-ai-chart-retry',
            prTitle: 'fix(ai): retry recoverable insight queries in chat answers',
            generationSteps: [
                'Reading the answer renderer and the query failure taxonomy',
                'Adding a single retry with backoff for recoverable errors',
                'Adding Run again to the error card for the rest',
                'Running the AI answer tests, 63 passing',
                'Preparing the diff for review',
            ],
            agentPrompt:
                'Fix RPT-1037: AI chat answers render a dead-end error card when their insight query fails, though most failures recover on retry. Add one automatic retry for recoverable errors and a Run again button on the card, behind ai-answer-query-retry.',
            changes: [
                {
                    file: 'answerVisualization.tsx',
                    snippet:
                        '   } catch (error) {\n+      if (isRecoverableQueryError(error) && attempt === 0) {\n+          return runQuery(node, { attempt: 1, delayMs: 800 })\n+      }\n       setQueryError(error)\n   }',
                },
            ],
            monitoringCriteria: 'error cards per answer under 0.5%, no added answer latency at p95',
        },
    },

    'RPT-1035': {
        observation: {
            label: 'Slack connections ending in a silent bounce',
            unit: 'per hour',
            chart: {
                series: [
                    {
                        name: 'Denied callbacks',
                        color: 'danger',
                        points: [1, 0, 1, 1, 0, 1, 2, 1, 1, 2, 1, 1, 2, 1, 2, 1, 1, 2, 1, 2, 2, 1, 2, 2],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per hour',
            },
            liveRange: [1, 3],
        },
        evidence: [
            {
                label: 'OAuth callbacks',
                title: '214 denied callbacks in 60 days',
                detail: 'Every failure branch ends the same way: a transient toast, then a redirect to where the user started.',
            },
            {
                label: 'Copy',
                title: 'The toast blames the user for canceling',
                detail: 'Slack also returns access_denied for workspaces that gate installs behind admin approval.',
            },
            {
                label: 'Analytics gap',
                title: 'Nothing is captured on the denial path',
                detail: 'We cannot tell an admin-approval workspace from a genuine cancellation.',
            },
        ],
        timeline: [
            {
                label: 'Denial pattern isolated to approval-gated workspaces',
                time: 'Aug 16',
                chip: 'cohort',
                color: 'muted',
            },
            { label: 'Anomaly detected, case opened', time: 'Aug 17 08:50', chip: 'auto', color: 'muted' },
            { label: 'Report published', time: 'Aug 17 09:12', chip: '22 min', color: 'success' },
        ],
        verdictHeadline: 'A failed Slack connect looks exactly like the user changed their mind',
        problem: [
            'People connecting Slack from a workspace that requires admin approval come back from the OAuth flow to the page they started on, with a toast that assumes they clicked cancel. Nothing tells them an approval request is the actual next step.',
            'Because the denial branch captures no event, the funnel cannot separate approval-gated workspaces from real cancellations, so this failure has been invisible in the connect metrics.',
        ],
        impactTiles: [
            { value: '88', label: 'people bounced', note: '60 days' },
            { value: '214', label: 'denied callbacks', note: '60 days' },
            { value: '0', label: 'events captured on the path', note: 'the funnel is blind here' },
        ],
        howWeKnow: [
            'The denied callbacks concentrate in workspaces whose Slack metadata shows install approval turned on.',
            'The callback handler routes every failure to the same toast-and-redirect branch with no capture call.',
            'Connect completion for those workspaces is near zero while other workspaces complete normally.',
        ],
        fix: {
            summary:
                'Soften the denial copy so it explains the admin-approval path, capture an event on every failure branch, and keep the user on a page that says what happens next.',
            flagKey: 'slack-connect-denial-path',
            branch: 'fix/rpt-1035-slack-denial-path',
            prTitle: 'fix(integrations): explain admin-gated Slack installs instead of bouncing',
            generationSteps: [
                'Reading the OAuth callback handler and the denial copy',
                'Splitting admin-approval denials from cancellations',
                'Capturing an event on every failure branch',
                'Running the integrations tests, 58 passing',
                'Preparing the diff for review',
            ],
            agentPrompt:
                'Fix RPT-1035: denied Slack OAuth callbacks bounce users back silently and capture nothing. Explain the admin-approval path in the failure copy, capture each failure branch, and keep the user on a page with a next step, behind slack-connect-denial-path.',
            changes: [
                {
                    file: 'integrationsLogic.ts',
                    snippet:
                        "   case 'access_denied':\n+      posthog.capture('integration oauth denied', { kind, reason })\n-      lemonToast.error(oauthCallbackErrors.access_denied)\n+      lemonToast.error(deniedCopyFor(kind, reason))\n       break",
                },
            ],
            monitoringCriteria:
                'denial events captured on 100% of failures, connect completion up for gated workspaces',
        },
    },

    'RPT-1031': {
        observation: {
            label: 'People hitting an untraceable dashboard tile error',
            unit: 'per hour',
            chart: {
                series: [
                    {
                        name: 'Tile error views',
                        color: 'danger',
                        points: [
                            21, 24, 22, 28, 31, 29, 35, 38, 41, 44, 48, 52, 55, 59, 62, 66, 64, 69, 72, 71, 75, 78, 76,
                            80,
                        ],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per hour',
                annotations: [{ index: 21, label: 'detected', color: 'accent', labelAnchor: 'end' }],
            },
            liveRange: [70, 88],
        },
        screenshot: {
            kind: 'dashboard-tile',
            urlHint: 'us.posthog.com/dashboard/214',
            source: 'from session replay 018f-d3a2',
        },
        evidence: [
            {
                label: 'Autocapture',
                title: '1,708 people saw the failed tile in one day',
                detail: 'Concentrated on shared dashboards, where the viewer cannot edit or debug the query.',
            },
            {
                label: 'Session replay',
                title: 'Try again is clicked and fails again',
                detail: 'The button re-runs the identical query with the identical inputs, so it cannot succeed.',
            },
            {
                label: 'Support',
                title: '6 tickets, none traceable',
                detail: 'The tile shows no error code and no query id, so support has nothing to search for.',
            },
        ],
        timeline: [
            { label: 'Tile failures start climbing', time: 'Aug 19 14:00', chip: 'trend', color: 'danger' },
            { label: 'Anomaly detected, case opened', time: 'Aug 19 22:10', chip: 'auto', color: 'muted' },
            { label: 'Report published', time: 'Aug 19 22:31', chip: '21 min', color: 'success' },
        ],
        verdictHeadline: 'A failed dashboard tile gives the viewer nothing to act on',
        problem: [
            'Failed tiles say there was a problem completing the query, and stop there. No error code, no query id, no timestamp. The Try again button re-runs the same query with the same inputs, so when the failure is deterministic it fails identically, and the viewer has no way to know that.',
            'The tile error rate has been climbing all day, and every ticket about it is untraceable because the one identifier support could search for is the thing the tile does not show.',
        ],
        impactTiles: [
            { value: '1,708', label: 'people in one day', note: 'saw a failed tile' },
            { value: '0', label: 'traceable reports', note: 'no error code or query id shown' },
            { value: '6', label: 'support tickets', note: 'all dead ends' },
        ],
        howWeKnow: [
            'The error component renders a fixed string and discards the structured error it receives.',
            'Replays show Try again failing identically, which matches deterministic query failures re-run with unchanged inputs.',
            'Ticket text quotes the generic message, and support logs show every search on it coming back empty.',
        ],
        fix: {
            summary:
                'Show the short error code and query id on the failed tile, and make Try again say when a retry cannot help. The id makes every future ticket traceable in one search.',
            flagKey: 'tile-error-details',
            branch: 'fix/rpt-1031-tile-error-details',
            prTitle: 'fix(dashboards): give failed tiles an error code and query id',
            generationSteps: [
                'Reading the tile error component and the query error shape',
                'Rendering the error code and query id on the tile',
                'Disabling Try again for deterministic failures with a reason',
                'Running the dashboard tests, 112 passing',
                'Preparing the diff for review',
            ],
            agentPrompt:
                'Fix RPT-1031: failed dashboard tiles show a generic message with no error code or query id, and Try again re-runs unwinnable queries. Surface both identifiers and gate retry on retryable errors, behind tile-error-details.',
            changes: [
                {
                    file: 'InsightErrorState.tsx',
                    snippet:
                        '   <p>There was a problem completing this query.</p>\n+  {queryId && <code className="text-xs">query {queryId}</code>}\n+  {errorCode && <code className="text-xs">{errorCode}</code>}',
                },
            ],
            monitoringCriteria: 'every tile error shows a query id, retry clicks on deterministic failures near zero',
        },
    },

    'RPT-1046': {
        observation: {
            label: 'People re-picking the date range right after opening a saved insight',
            unit: 'per hour',
            chart: {
                series: [
                    {
                        name: 'Range re-picks',
                        color: 'danger',
                        points: [
                            13, 15, 14, 12, 15, 13, 14, 15, 34, 46, 58, 63, 71, 76, 80, 84, 86, 89, 91, 93, 95, 97, 96,
                            99,
                        ],
                    },
                    {
                        name: 'Insights opened with the saved range intact',
                        color: 'muted',
                        dashed: true,
                        points: [
                            62, 64, 61, 63, 60, 62, 63, 61, 44, 33, 26, 21, 18, 15, 13, 12, 11, 10, 9, 9, 8, 8, 7, 7,
                        ],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per hour',
                baselineValue: 14,
                baselineLabel: 'baseline 14/hr',
                annotations: [
                    { index: 8, label: 'deploy 7c19ab4', color: 'danger' },
                    { index: 19, label: 'detected', color: 'accent', labelAnchor: 'end' },
                ],
            },
            liveRange: [92, 108],
        },
        occurrences: {
            label: 'Range re-picks within 10 seconds of opening a saved insight, hourly',
            values: [13, 15, 14, 12, 15, 13, 14, 15, 34, 46, 58, 63, 71, 76, 80, 84, 86, 89, 91, 93, 95, 97, 96, 99],
            alarmFromIndex: 8,
        },
        evidence: [
            {
                label: 'Product analytics',
                title: '2,140 range re-picks in 9 hours',
                detail: 'Almost every one lands within 10 seconds of the insight loading, before the first query returns.',
                bars: {
                    values: [13, 15, 14, 12, 15, 34, 46, 58, 63, 71, 76, 80, 84, 89, 91, 95, 97, 99],
                    alarmFromIndex: 5,
                },
            },
            {
                label: 'Session replay',
                title: '38 replays show the same correction',
                detail: 'Open the insight, glance at the chart, reopen the date picker, pick the same range again, wait through a second load.',
            },
            {
                label: 'Funnel',
                title: '1 in 5 leave before the second query finishes',
                detail: 'Insight opened to chart viewed, compared with the trailing 14-day baseline.',
            },
            {
                label: 'Saved insights',
                title: '1,180 saved insights hold a relative range',
                detail: 'Every one of them now serializes to absolute dates on save, so every one of them is affected.',
            },
            {
                label: 'Deploy diff',
                title: '7c19ab4 resolves the range before saving',
                detail: 'The relative range is turned into absolute dates in the save path instead of at query time.',
            },
        ],
        timeline: [
            {
                label: 'Deploy moves range resolution into the save path',
                time: 'Aug 19 16:10',
                chip: '7c19ab4',
                color: 'danger',
            },
            { label: 'First re-pick cluster on saved insights', time: 'Aug 19 16:26', chip: '+16 min', color: 'muted' },
            { label: 'Re-picks pass 5x baseline', time: 'Aug 20 00:00', chip: '5x', color: 'muted' },
            { label: 'Anomaly detected, case opened', time: 'Aug 20 00:52', chip: 'auto', color: 'muted' },
            { label: 'Report published', time: 'Aug 20 01:14', chip: '22 min', color: 'success' },
        ],
        verdictHeadline: 'Saved insights forget that their date range was relative',
        problem: [
            'An insight saved on a relative range such as last 30 days should reopen on the last 30 days from today. Since deploy 7c19ab4 the range is resolved to absolute dates when the insight is saved, so it reopens on the 30 days that ended the day it was saved. The picker still displays the relative label, which is why the chart does not read as stale.',
            'The cost is a second query on almost every open. People notice the dates are old, pick the range again, and wait through another load. About one in five close the insight before that second query returns, so the number they came for never appears.',
        ],
        replayCaption:
            'One of 38 matching replays: the chart loads, the date picker opens 6 seconds later, and the same range is picked again.',
        impactTiles: [
            { value: '932', label: 'people opened a stale insight', note: 'in 9 hours' },
            { value: '2,140', label: 'range re-picks', note: 'median 1 per open' },
            { value: '1,180', label: 'saved insights affected', note: 'every relative range' },
            { value: '19%', label: 'leave before the re-run finishes', note: 'was 4%' },
        ],
        howWeKnow: [
            'The first re-pick cluster lands 16 minutes after deploy 7c19ab4, and every affected session runs code from that deploy.',
            'The diff resolves the relative range into absolute dates in the save path, so the stored filter no longer carries the relative value.',
            'Insights saved before the deploy still reopen on the right range, because their stored filter kept the relative value.',
            'All 38 matching replays show a re-pick within 20 seconds of the insight loading, and 7 of them end without a second chart.',
        ],
        causeDiff: {
            title: 'The change that introduced it, in 7c19ab4',
            snippet:
                '   const filters = cleanFilters(values.filters)\n+  filters.date_from = resolveRelativeDate(filters.date_from)\n+  filters.date_to = resolveRelativeDate(filters.date_to)\n   await api.insights.update(insightId, { filters })',
        },
        fix: {
            summary:
                'Keep the relative range in the saved filter and resolve it when the query runs, so an insight reopens on the range its author picked. Behind a flag so the rollout can halt itself if re-picks do not fall.',
            flagKey: 'insight-relative-range-persist',
            branch: 'fix/rpt-1046-relative-date-ranges',
            prTitle: 'fix(insights): keep relative date ranges relative when saving',
            generationSteps: [
                'Reading the insight save path and the 7c19ab4 diff',
                'Removing date resolution from the save path',
                'Resolving the range at query time instead',
                'Running the insights test suite, 214 passing',
                'Preparing the diff for review',
            ],
            agentPrompt:
                'Fix RPT-1046: saved insights resolve their relative date range to absolute dates on save, so they reopen on stale dates. Keep the relative value in the stored filter, resolve it at query time, and gate the change behind insight-relative-range-persist.',
            changes: [
                {
                    file: 'insightSaveLogic.ts',
                    snippet:
                        '   const filters = cleanFilters(values.filters)\n-  filters.date_from = resolveRelativeDate(filters.date_from)\n-  filters.date_to = resolveRelativeDate(filters.date_to)\n   await api.insights.update(insightId, { filters })',
                },
                {
                    file: 'insightQueryLogic.ts',
                    snippet:
                        '   const filters = insight.filters\n+  const dateFrom = resolveRelativeDate(filters.date_from)\n+  const dateTo = resolveRelativeDate(filters.date_to)\n   return buildQuery({ ...filters, date_from: dateFrom, date_to: dateTo })',
                    note: 'The range is resolved for the query and never written back to the saved insight.',
                },
            ],
            monitoringCriteria: 'range re-picks back to baseline, insight abandonment under 5%',
        },
    },

    'RPT-1045': {
        observation: {
            label: 'Survey completions recorded with no answers in them',
            unit: 'per hour',
            chart: {
                series: [
                    {
                        name: 'Empty completions',
                        color: 'danger',
                        points: [4, 3, 5, 4, 4, 6, 3, 5, 4, 4, 5, 3, 4, 5, 4, 3, 5, 4, 4, 5, 3, 4, 5, 4],
                    },
                    {
                        name: 'Completions with at least one answer',
                        color: 'muted',
                        dashed: true,
                        points: [
                            26, 24, 27, 25, 28, 26, 25, 27, 24, 26, 28, 25, 27, 26, 24, 27, 25, 26, 28, 25, 27, 26, 25,
                            27,
                        ],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per hour',
            },
            liveRange: [3, 6],
        },
        occurrences: {
            label: 'Empty completions, hourly',
            values: [4, 3, 5, 4, 4, 6, 3, 5, 4, 4, 5, 3, 4, 5, 4, 3, 5, 4, 4, 5, 3, 4, 5, 4],
            alarmFromIndex: 0,
        },
        evidence: [
            {
                label: 'Surveys',
                title: '1,380 completions with zero answers in 14 days',
                detail: 'Every one of them closed the popup from the last step instead of submitting it.',
                bars: {
                    values: [4, 3, 5, 4, 4, 6, 3, 5, 4, 5, 3, 4, 5, 3, 5, 4, 5, 4],
                    alarmFromIndex: 0,
                },
            },
            {
                label: 'Surveys',
                title: 'The dismissal handler runs the completion path',
                detail: 'Closing from the last step calls the same code as submitting, so it sends the response and shows the thank-you step.',
            },
            {
                label: 'Product analytics',
                title: 'Reported response rate reads 12 points high',
                detail: 'A 41% completion rate against a 29% answered rate over the same 14 days.',
            },
            {
                label: 'Product analytics',
                title: '4 of 11 live surveys carry the skew',
                detail: 'The skew grows with question count, because more steps means more chances to close on the last one.',
            },
        ],
        timeline: [
            { label: 'Multi-step survey popup ships', time: 'Aug 4', chip: 'v3', color: 'muted' },
            { label: 'First empty completion recorded', time: 'Aug 5 08:12', chip: 'auto', color: 'danger' },
            { label: 'Empty completions pass 1,000', time: 'Aug 17', chip: '1k', color: 'muted' },
            { label: 'Anomaly detected, case opened', time: 'Aug 19 03:29', chip: 'auto', color: 'muted' },
            { label: 'Report published', time: 'Aug 19 03:51', chip: '22 min', color: 'success' },
        ],
        verdictHeadline: 'Closing a survey on the last step counts as completing it',
        problem: [
            'A multi-question survey popup treats the close icon on the last step as a submit. The dismissal handler falls through into the completion path, so it sends the survey response event, shows the thank-you step, and stores a response with no answers in it.',
            'Nobody sees this happen. The person dismissing the survey gets a thank-you screen they did not ask for, and the team reading the results gets blank rows that look like a rendering problem next to a completion rate 12 points higher than the answers support.',
        ],
        impactTiles: [
            { value: '1,380', label: 'empty completions stored', note: 'in 14 days' },
            { value: '510', label: 'people counted as respondents', note: 'answered nothing' },
            { value: '12 pts', label: 'overstated completion rate', note: '41% against 29%' },
        ],
        howWeKnow: [
            'Every empty response carries the survey response event with an answers payload that has no entries.',
            'All of them come from the last step of a multi-question survey, and single-question surveys are unaffected.',
            'Removing the empty responses drops the reported completion rate from 41% to 29% across the same 14 days.',
            'The skew per survey grows with question count, which matches a failure that needs a last step to reach.',
        ],
        causeDiff: {
            title: 'The dismissal path lost its early return',
            snippet:
                '   function onDismiss() {\n       closePopup()\n-      return\n   }\n   sendSurveyResponse(answers)\n   showThankYou()',
        },
        fix: {
            summary:
                'Separate dismissal from submission, so closing the popup records a dismissal and nothing else. Responses already stored without answers stay in the list, marked as dismissals, and stop counting toward the completion rate.',
            flagKey: 'survey-dismiss-not-complete',
            branch: 'fix/rpt-1045-survey-dismissal',
            prTitle: 'fix(surveys): stop counting a dismissal as a completed response',
            generationSteps: [
                'Reading the survey popup step handlers',
                'Restoring the early return on the dismissal path',
                'Recording a dismissal event instead',
                'Excluding answerless responses from the completion rate',
                'Running the surveys test suite, 64 passing',
            ],
            agentPrompt:
                'Fix RPT-1045: dismissing a multi-question survey from the last step falls through into the completion path, so it sends a survey response with no answers and shows the thank-you step. Record a dismissal instead, exclude answerless responses from the completion rate, and gate the change behind survey-dismiss-not-complete.',
            changes: [
                {
                    file: 'surveyPopupLogic.ts',
                    snippet:
                        '   function onDismiss() {\n       closePopup()\n+      sendSurveyDismissed()\n+      return\n   }\n   sendSurveyResponse(answers)\n   showThankYou()',
                },
                {
                    file: 'surveyResultsLogic.ts',
                    snippet:
                        '-  const completed = responses.length\n+  const completed = responses.filter((response) => response.answers.length > 0).length',
                    note: 'Answerless responses stay visible as dismissals instead of inflating the completion rate.',
                },
            ],
            monitoringCriteria: 'empty completions at zero, completion rate within 1 point of the answered rate',
        },
    },

    'RPT-1043': {
        observation: {
            label: 'Cohort saves that leave a property filter with no value',
            unit: 'per hour',
            chart: {
                series: [
                    {
                        name: 'Saves with an empty filter',
                        color: 'danger',
                        points: [2, 3, 2, 4, 3, 4, 5, 4, 6, 5, 7, 6, 8, 7, 9, 8, 10, 9, 11, 10, 12, 11, 13, 12],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per hour',
                baselineValue: 3,
                baselineLabel: 'baseline 3/hr',
                annotations: [{ index: 6, label: 'filter builder rework', color: 'danger' }],
            },
            liveRange: [10, 15],
        },
        occurrences: {
            label: 'Cohort saves with an empty property filter, hourly',
            values: [2, 3, 2, 4, 3, 4, 5, 4, 6, 5, 7, 6, 8, 7, 9, 8, 10, 9, 11, 10, 12, 11, 13, 12],
            alarmFromIndex: 6,
        },
        evidence: [
            {
                label: 'Support tickets',
                title: '19 tickets say a cohort went to zero',
                detail: 'Each one describes editing a working cohort and finding it empty afterwards. None mentions an error, because there is not one.',
            },
            {
                label: 'Product analytics',
                title: '146 cohorts hold a condition with no value',
                detail: 'All of them calculate to 0 people, and 92 of them had a non-zero count before the edit.',
                bars: {
                    values: [2, 3, 2, 4, 3, 5, 4, 6, 7, 6, 8, 9, 8, 10, 11, 10, 12, 13],
                    alarmFromIndex: 5,
                },
            },
            {
                label: 'Product analytics',
                title: '61 of the 146 were rebuilt from scratch',
                detail: 'A new cohort with the same name appears within a day, which is the only workaround available.',
            },
            {
                label: 'Validation',
                title: 'The value field is optional in the save path',
                detail: 'The builder checks that a property and an operator are set, and never checks that an operator needing a value has one.',
            },
        ],
        timeline: [
            { label: 'Property filter builder rework ships', time: 'Aug 15 11:20', chip: '2e70c93', color: 'danger' },
            { label: 'First cohort saved with an empty filter', time: 'Aug 15 11:40', chip: '+20 min', color: 'muted' },
            { label: 'Support tickets pass 10', time: 'Aug 17', chip: '10', color: 'muted' },
            { label: 'Anomaly detected, case opened', time: 'Aug 18 04:08', chip: 'auto', color: 'muted' },
            { label: 'Report published', time: 'Aug 18 04:30', chip: '22 min', color: 'success' },
        ],
        verdictHeadline: 'An empty property filter saves as a condition that matches nobody',
        problem: [
            'The cohort filter builder lets a property condition save with an operator that needs a value and no value in it. Validation only checks that a property and an operator are set, so the save succeeds, the condition compiles to a comparison against an empty string, and the cohort matches nobody.',
            'What the person gets back is a cohort that reads 0 people, with no error, no warning, and no way to tell which condition emptied it. Most assume they broke the cohort and build a new one, which is why 61 of the 146 affected cohorts already have a duplicate.',
        ],
        impactTiles: [
            { value: '146', label: 'cohorts matching nobody', note: 'since Aug 15' },
            { value: '92', label: 'had people before the edit', note: 'a real regression' },
            { value: '19', label: 'support tickets', note: 'none got a cause' },
            { value: '61', label: 'rebuilt from scratch', note: 'the only workaround' },
        ],
        howWeKnow: [
            'Every affected cohort has at least one property condition whose operator needs a value and whose value is empty.',
            'The first one appears the day the filter builder rework shipped, and none exists before it.',
            'Re-running the same definition with the empty condition removed returns the person count the cohort had before the edit.',
            'All 19 tickets attach a cohort of this shape, and none of them reports an error message.',
        ],
        causeDiff: {
            title: 'The rework dropped the value check, in 2e70c93',
            snippet:
                '   if (!condition.property || !condition.operator) {\n       return false\n   }\n-  if (operatorNeedsValue(condition.operator) && isEmpty(condition.value)) {\n-      return false\n-  }\n   return true',
        },
        fix: {
            summary:
                'Block the save when an operator that needs a value does not have one, and name the condition that is blocking it. The 146 cohorts already saved this way get a banner on the cohort page pointing at the condition that emptied them.',
            flagKey: 'cohort-empty-filter-validation',
            branch: 'fix/rpt-1043-empty-cohort-filters',
            prTitle: 'fix(cohorts): block saving a property filter with no value',
            generationSteps: [
                'Reading the cohort filter validation and the 2e70c93 diff',
                'Restoring the value check for operators that need one',
                'Wiring the failing condition into the save button reason',
                'Flagging cohorts already saved with an empty condition',
                'Running the cohort test suite, 118 passing',
            ],
            agentPrompt:
                'Fix RPT-1043: a cohort property condition saves with an operator that needs a value and no value, so the cohort matches nobody and shows 0 people with no error. Restore the value check, name the failing condition on the save button, and gate the change behind cohort-empty-filter-validation.',
            changes: [
                {
                    file: 'cohortFiltersLogic.ts',
                    snippet:
                        '   if (!condition.property || !condition.operator) {\n       return false\n   }\n+  if (operatorNeedsValue(condition.operator) && isEmpty(condition.value)) {\n+      return false\n+  }\n   return true',
                },
                {
                    file: 'CohortEdit.tsx',
                    snippet:
                        '   <LemonButton\n       type="primary"\n+      disabledReason={firstIncompleteCondition ?? undefined}\n       onClick={saveCohort}\n   >',
                    note: 'The save button now names the condition that is missing a value instead of saving a cohort that matches nobody.',
                },
            ],
            monitoringCriteria: 'no new cohorts saved with an empty condition, cohort tickets back to baseline',
        },
    },

    'RPT-1028': {
        observation: {
            label: 'Stackless Firefox errors landing in the catch-all issue',
            unit: 'per hour',
            chart: {
                series: [
                    {
                        name: 'Stackless captures',
                        color: 'danger',
                        points: [
                            58, 61, 59, 63, 60, 62, 64, 61, 63, 60, 62, 59, 61, 58, 44, 31, 22, 15, 11, 8, 6, 5, 4, 4,
                        ],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per hour',
                baselineValue: 5,
                baselineLabel: 'target under 5/hr',
                annotations: [{ index: 14, label: 'fix shipped', color: 'success' }],
            },
            liveRange: [3, 6],
        },
        evidence: [
            {
                label: 'Error tracking',
                title: 'One issue absorbed 3,412 unrelated events',
                detail: 'Firefox network failures captured without a stack all group into the same untriageable bucket.',
            },
            {
                label: 'Fix',
                title: 'Synthetic stack fallback shipped 9 hours ago',
                detail: 'Captures without a stack now get one built from the capture site before grouping.',
            },
            {
                label: 'Verification',
                title: 'Grouping is being watched for 7 days',
                detail: 'Pass criteria: stackless captures under 5 per hour and no regrouping churn on existing issues.',
            },
        ],
        timeline: [
            { label: 'Catch-all issue crosses 3,000 events', time: 'Aug 14', chip: '3k', color: 'danger' },
            { label: 'Anomaly detected, case opened', time: 'Aug 15 08:20', chip: 'auto', color: 'muted' },
            { label: 'Report published', time: 'Aug 15 08:40', chip: '20 min', color: 'success' },
            { label: 'Synthetic stack fallback shipped', time: 'Aug 20 01:30', chip: 'merged', color: 'success' },
        ],
        verdictHeadline: 'Stackless errors were all becoming the same issue',
        problem: [
            'Firefox reports network failures through captureException without a stack, and grouping needs one. Everything stackless collapsed into a single issue that mixed dozens of unrelated pages, which made it impossible to triage and drowned real regressions in noise.',
            'A fallback that synthesizes a stack from the capture site shipped 9 hours ago. The chart above should stay at the new floor; if it climbs back, the fix did not hold.',
        ],
        impactTiles: [
            { value: '3,412', label: 'events in one issue', note: 'before the fix' },
            { value: '4/hr', label: 'stackless captures now', note: 'was ~60/hr' },
            { value: 'day 1 of 7', label: 'verification window', note: 'auto-resolves if it holds' },
        ],
        howWeKnow: [
            'Every event in the catch-all issue shares the no-stack capture path and nothing else.',
            'Stackless capture volume fell from about 60 to under 5 per hour within an hour of the fix deploying.',
            'New captures since the fix group into distinct issues by their synthesized top frame.',
        ],
        fix: {
            summary:
                'Already shipped: build a synthetic stack from the capture site when the error has none, so grouping has something real to hash. This page is now watching the fix hold.',
            initialPhase: 'launched',
            flagKey: 'synthetic-stack-fallback',
            branch: 'fix/rpt-1028-synthetic-stacks',
            prTitle: 'fix(error-tracking): synthesize a stack for stackless captures',
            generationSteps: [
                'Reading the capture path and the grouping hash inputs',
                'Building the synthetic frame from the capture site',
                'Hashing on the synthesized top frame',
                'Running the error tracking tests, 87 passing',
                'Preparing the diff for review',
            ],
            agentPrompt:
                'Fix RPT-1028: captures without a stack all group into one catch-all issue. Synthesize a stack from the capture site before grouping, behind synthetic-stack-fallback.',
            changes: [
                {
                    file: 'exceptionCapture.ts',
                    snippet: '   if (!error.stack) {\n+      error.stack = syntheticStackFromCaptureSite()\n   }',
                },
            ],
            monitoringCriteria: 'stackless captures under 5/hr, no regrouping churn on existing issues',
        },
    },

    'RPT-1019': {
        observation: {
            label: 'Server-side flag calls evaluating the wrong variant',
            unit: 'per hour',
            chart: {
                series: [
                    {
                        name: 'Wrong variant evaluations',
                        color: 'success',
                        points: [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    },
                    {
                        name: 'Calls evaluating against the properties the caller sent',
                        color: 'muted',
                        dashed: true,
                        points: [
                            262, 271, 268, 275, 259, 283, 277, 265, 288, 272, 269, 281, 276, 264, 279, 285, 270, 258,
                            274, 282, 267, 273, 286, 271,
                        ],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per hour',
            },
            liveRange: [0, 0],
        },
        evidence: [
            {
                label: 'Feature flags',
                title: '0 wrong evaluations in 7 days',
                detail: 'Down from about 11 an hour before the fix. Every call that sends person properties now evaluates against the properties the caller sent.',
            },
            {
                label: 'Feature flags',
                title: '1,930 people were served a wrong variant',
                detail: 'Over the 10 days between the cause shipping on Jul 30 and the fix shipping on Aug 11.',
            },
            {
                label: 'Session replay',
                title: '24 replays show the wrong experience',
                detail: 'Paid accounts landing on the free-plan variant of a gated screen, because the plan property was overwritten.',
            },
            {
                label: 'Support tickets',
                title: 'About one a week still arrives',
                detail: 'From clients that cached a wrong variant before the fix. Those clear on their own as sessions expire.',
            },
        ],
        timeline: [
            {
                label: 'GeoIP enrichment reordered ahead of caller properties',
                time: 'Jul 30 09:02',
                chip: 'b2d47e1',
                color: 'danger',
            },
            { label: 'First wrong variant served', time: 'Jul 30 09:11', chip: '+9 min', color: 'muted' },
            { label: 'Detected, case opened', time: 'Aug 9 06:20', chip: 'auto', color: 'muted' },
            { label: 'Report published', time: 'Aug 9 06:47', chip: '27 min', color: 'muted' },
            { label: 'Fix shipped', time: 'Aug 11', chip: 'merged', color: 'success' },
            { label: 'Verified for 7 days, resolved', time: 'Aug 18', chip: 'auto', color: 'success' },
        ],
        verdictHeadline: 'GeoIP enrichment overwrote the person properties the caller sent',
        problem: [
            'Flag calls from server SDKs can pass their own person properties with the request. Deploy b2d47e1 moved GeoIP enrichment ahead of those properties, so enrichment overwrote what the caller sent, and any flag targeted on a caller-supplied property matched the wrong rule.',
            'The fix reorders enrichment so it only fills properties the caller did not send. It shipped on Aug 11 and held for the full 7-day verification window, so this report resolved itself on Aug 18. The closing numbers are in the resolution.',
        ],
        replayCaption: 'One of 24 matching replays: a paid account lands on the free-plan variant of a gated screen.',
        impactTiles: [
            { value: '1,930', label: 'people served a wrong variant', note: 'over 10 days' },
            { value: '0', label: 'wrong evaluations now', note: '7 days verified' },
            { value: '4.1%', label: 'of server SDK calls affected', note: 'now 0%' },
            { value: '2 days', label: 'from report to fix', note: '10 days from the cause' },
        ],
        howWeKnow: [
            'The first wrong evaluation lands 9 minutes after deploy b2d47e1, and every affected call ran through the reordered enrichment.',
            'Only calls that sent person properties are affected, and calls that sent none evaluated correctly throughout.',
            'Re-running the affected calls against the properties the caller sent returns the variant those people should have seen.',
            'Seven days of flag calls after the fix show every evaluation matching the caller-supplied properties.',
        ],
        causeDiff: {
            title: 'The change that introduced it, in b2d47e1',
            snippet:
                '-  const properties = { ...geoipProperties, ...callerProperties }\n+  const properties = { ...callerProperties, ...geoipProperties }',
        },
    },

    'RPT-1023': {
        observation: {
            label: 'Project settings p75 load time',
            unit: 'ms',
            chart: {
                series: [
                    {
                        name: 'p75 LCP',
                        color: 'danger',
                        points: [
                            3180, 3240, 3150, 3300, 3220, 3280, 3350, 3260, 3310, 3400, 3380, 3450, 4620, 4700, 4680,
                            4750, 4690, 4720, 4660, 4710, 4680, 4650, 4700, 4670,
                        ],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'ms',
                baselineValue: 3300,
                baselineLabel: 'prior 13-day band',
                annotations: [{ index: 12, label: 'step change', color: 'danger' }],
            },
            liveRange: [4550, 4800],
        },
        evidence: [
            {
                label: 'Web vitals',
                title: 'p75 stepped from ~3.3s to ~4.7s',
                detail: 'A step, not a drift, which usually means one cause rather than gradual load.',
            },
            {
                label: 'Dispute',
                title: 'The step tracks one enterprise org',
                detail: 'J. Doe: the slow samples concentrate in a single org with an unusually large config payload.',
            },
        ],
        timeline: [
            { label: 'p75 crosses into the poor band', time: 'Aug 15', chip: '4.7s', color: 'danger' },
            {
                label: 'Report published, blaming the settings rework',
                time: 'Aug 16 10:12',
                chip: 'auto',
                color: 'muted',
            },
            { label: 'Disputed with a corrected cause', time: 'Aug 18 15:40', chip: 'human', color: 'success' },
        ],
        verdictHeadline: 'Disputed: the slow settings loads track one org, not the rework',
        problem: [
            'The original report attributed the settings load-time step to the settings rework that shipped the same week. J. Doe disputed it: the slow samples concentrate in a single enterprise org whose config payload is far larger than typical, and the rework is not in the slow path.',
            'The engine is re-running the analysis with the org excluded to confirm the corrected attribution. If the step disappears, the finding becomes a payload-size issue for that org rather than a frontend regression.',
        ],
        impactTiles: [
            { value: '4.7s', label: 'p75 LCP now', note: 'was ~3.3s' },
            { value: '1 org', label: 'holds most slow samples', note: 'per the dispute' },
            { value: 'queued', label: 're-analysis', note: 'org-excluded baseline' },
        ],
        howWeKnow: [
            'The dispute traced sample-level timings: the slow tail concentrates in one org identifier.',
            'The settings rework does not appear in the flame data for the slow samples.',
            'Excluding the org in a quick cut returns p75 to the prior band, pending the full re-run.',
        ],
    },

    'RPT-1015': {
        observation: {
            label: 'Replays showing doubled video controls',
            unit: 'per day',
            chart: {
                series: [
                    {
                        name: 'Affected replays viewed',
                        color: 'muted',
                        points: [6, 8, 7, 9, 6, 8, 7, 6, 9, 7, 8, 6, 7, 8, 6, 9, 7, 8, 7, 6, 8, 7, 6, 7],
                    },
                ],
                pointLabels: HOURLY_24,
                xLabels: HOURLY_X_LABELS,
                unit: 'per day',
            },
            liveRange: [5, 9],
        },
        evidence: [
            {
                label: 'Session replay',
                title: 'Chrome default controls render over custom players',
                detail: 'The scriptless player iframe re-enables native controls the recorded site had hidden.',
            },
            {
                label: 'Scope',
                title: 'Playback itself is unaffected',
                detail: 'The doubled controls are cosmetic; the recording plays correctly underneath.',
            },
        ],
        timeline: [
            { label: 'Report published', time: 'Aug 13 04:33', chip: 'auto', color: 'muted' },
            { label: 'Dismissed with reason', time: 'Aug 14 09:10', chip: 'human', color: 'success' },
        ],
        verdictHeadline: 'Dismissed: cosmetic, and a general fix risks hiding real controls',
        problem: [
            'Replays of pages with custom video players show Chrome default controls stacked on the site controls, so the recording does not exactly match the live page. Playback works; the mismatch is visual.',
            'A. Roe dismissed it: suppressing native controls across the player iframe could hide controls that recorded sites genuinely use, which is a worse failure than the cosmetic one. Kept for audit and revisit if volume grows.',
        ],
        impactTiles: [
            { value: '~7', label: 'affected replays viewed per day', note: 'flat' },
            { value: '0', label: 'people blocked', note: 'playback unaffected' },
        ],
        howWeKnow: [
            'The affected replays share the scriptless player path and pages with a video element.',
            'No support tickets or watch-abandonment signal is attached to the affected replays.',
        ],
    },
}
