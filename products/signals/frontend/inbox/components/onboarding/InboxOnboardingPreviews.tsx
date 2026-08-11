import { LemonTag, Tooltip } from '@posthog/lemon-ui'

import { dayjs } from 'lib/dayjs'

import { SignalReport, SignalReportStatus } from '../../types'
import { ReportCard } from '../cards/ReportCard'
import { playMeep } from './meep'

/**
 * Onboarding previews that render the *real* inbox `ReportCard` (the very component the Pull
 * requests / Reports tabs use), fed mock data – so they read as the genuine article rather than a
 * lookalike. Because they look real, they're marked plainly as examples: an "Example" tag sits on
 * each card, the card itself is made non-interactive (so its Review/Archive buttons don't offer
 * live hover states or misleading tooltips), and a single click surface explains that the real work
 * arrives once you run the setup command. The meep stays as flair, but it's no longer the only sign
 * a click did anything.
 *
 * The sample work is a wink at Silicon Valley (the show): Pied Piper's middle-out compression and
 * the ever-looming Hooli.
 */

// Timestamps are relative to "now" at render time (not a fixed calendar date) so `ReportCard`'s
// `TZLabel` always reads as just-landed work ("2 hours ago") instead of drifting to "months ago".
// Subtracting from the current clock also keeps the relative label stable in snapshot/VR runs.
const landedHoursAgo = (hours: number): string => dayjs().subtract(hours, 'hours').toISOString()

// A shippable fix Pied Piper's agents could open against the compression engine.
const PULL_REQUEST_SAMPLE: Omit<SignalReport, 'created_at' | 'updated_at'> = {
    id: 'onboarding-preview-pr',
    title: 'fix(compression): stop 4K streams dropping to single-threaded encode',
    summary:
        'Middle-out throughput fell 41% above 2160p after the Anton migration. The Weissman score slid from 5.2 to 2.9 and p95 encode time tripled. This repins the chunk scheduler and restores both to pre-migration numbers.',
    status: SignalReportStatus.READY,
    total_weight: 0,
    signal_count: 3,
    relevant_user_count: null,
    artefact_count: 0,
    is_suggested_reviewer: false,
    priority: 'P1',
    source_products: ['session_replay'],
    implementation_pr_url: 'https://github.com/PiedPiper/pipernet/pull/486',
}

// A "needs your call" report: no clean code change, a judgment to make.
const REPORT_SAMPLE: Omit<SignalReport, 'created_at' | 'updated_at'> = {
    id: 'onboarding-preview-report',
    title: 'Hooli traffic is hammering the Pipernet beta. Throttle or let it ride?',
    summary:
        "Sign-ups from Hooli IP ranges jumped 6× overnight and mostly bounce at onboarding. This could be Gavin's team load-testing us or real interest worth keeping. Review it before we rate-limit.",
    status: SignalReportStatus.READY,
    total_weight: 0,
    signal_count: 5,
    relevant_user_count: null,
    artefact_count: 0,
    is_suggested_reviewer: false,
    priority: 'P2',
    actionability: 'requires_human_input',
    source_products: ['error_tracking', 'session_replay'],
}

/**
 * Wraps a real `ReportCard` and makes it legibly a sample. The card is rendered non-interactive
 * (`pointer-events-none`, `aria-hidden`) so its Review/Archive buttons and links no longer offer
 * live hover states or misleading tooltips ("Archive this report") that invite dead clicks. An
 * "Example" tag labels it at a glance, and a single click surface on top plays the meep flair while
 * a tooltip explains that real work lands here once the setup command runs.
 */
function PreviewCard({ report, tabKey }: { report: SignalReport; tabKey: 'pulls' | 'reports' }): JSX.Element {
    return (
        // `@container` so ReportCard's `@lg:` row layout resolves against the preview width (it has no
        // inbox-list container here). `role="presentation"` – the whole thing is decorative.
        <div role="presentation" className="@container relative">
            {/* The real card in preview mode: no detail link, no focusable actions. That keeps the
                sample report id (which 404s) out of reach – nobody can click or tab into it – on top
                of the `pointer-events-none` and overlay below. */}
            <div aria-hidden className="pointer-events-none">
                <ReportCard report={report} tabKey={tabKey} preview />
            </div>

            {/* Always-visible label so the sample reads as a sample, not live work. Sits on the top
                border and stays out of the way of clicks (handled by the overlay below). */}
            <LemonTag type="highlight" size="small" className="pointer-events-none absolute -top-2 left-4 z-20">
                Example
            </LemonTag>

            {/* One interactive surface over the whole card: a click plays the meep flair, and the
                tooltip is the real signal – it says this is a preview and how to get the real thing. */}
            <Tooltip title="This is an example. Run the command above to get real ones in your inbox.">
                <button
                    type="button"
                    aria-label="Example card – run the setup command to get real ones in your inbox"
                    className="absolute inset-0 z-10 h-full w-full cursor-pointer"
                    onClick={() => playMeep()}
                />
            </Tooltip>
        </div>
    )
}

export function PullRequestPreview(): JSX.Element {
    const landed = landedHoursAgo(2)
    return <PreviewCard report={{ ...PULL_REQUEST_SAMPLE, created_at: landed, updated_at: landed }} tabKey="pulls" />
}

export function ReportPreview(): JSX.Element {
    const landed = landedHoursAgo(4)
    return <PreviewCard report={{ ...REPORT_SAMPLE, created_at: landed, updated_at: landed }} tabKey="reports" />
}
