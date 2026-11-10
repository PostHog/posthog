import { LemonTagType } from 'lib/lemon-ui/LemonTag'

import { DigestRunApi, DigestRunStatusEnumApi } from '../../generated/api.schemas'

const STATUS_DISPLAY: Record<DigestRunStatusEnumApi, { type: LemonTagType; label: string }> = {
    pending: { type: 'default', label: 'Pending' },
    completed: { type: 'success', label: 'Posted' },
    failed: { type: 'danger', label: 'Failed' },
}

/**
 * What happened to a digest run.
 *
 * A run that found nothing worth summarizing completes without calling Slack, and still stamps
 * posted_at. Only slack_message_ts proves a message exists, so it decides "Posted" against
 * "Nothing to post" — otherwise the table claims a Slack post the reader will not find.
 */
export function digestStatusDisplay(run: DigestRunApi): { type: LemonTagType; label: string } {
    if (run.status === DigestRunStatusEnumApi.Completed && !run.slack_message_ts) {
        return { type: 'muted', label: 'Nothing to post' }
    }
    return STATUS_DISPLAY[run.status] ?? { type: 'muted', label: run.status }
}

/**
 * Where a digest went, as a person would say it.
 *
 * slack_channel_name is display-only and can be blank, so the ID is the fallback. A run with
 * neither would otherwise render as an empty cell.
 *
 * Only a name takes the "#". A channel ID is not a channel name, so "#C045EF6GH" names nothing a
 * reader can search Slack for. Backfilled runs are where a blank name actually shows up.
 */
export function digestDestinationLabel(run: DigestRunApi): string {
    return run.slack_channel_name ? `#${run.slack_channel_name}` : run.slack_channel_id
}

// A real Slack ts is "<seconds>.<micros>". digest_runs.py stores "posted" when Slack accepted the
// message but returned no ts, and a link built from that opens nothing.
const SLACK_MESSAGE_TS_PATTERN = /^\d+\.\d+$/

/** Permalink to the posted digest, in the `/archives/<channel>/p<ts without the dot>` form. */
export function digestSlackMessageUrl(run: DigestRunApi): string | null {
    if (!run.slack_channel_id || !SLACK_MESSAGE_TS_PATTERN.test(run.slack_message_ts)) {
        return null
    }
    return `https://app.slack.com/archives/${run.slack_channel_id}/p${run.slack_message_ts.replace('.', '')}`
}

const EMPTY_SUMMARY: DigestRunApi['summary'] = { headline: '', prs: [] }

/** The digest content, empty when an API pod from the previous release answered without it during a deploy. */
export function digestSummary(run: DigestRunApi): DigestRunApi['summary'] {
    return run.summary ?? EMPTY_SUMMARY
}

export function digestRunHasDetails(run: DigestRunApi): boolean {
    const { headline, prs } = digestSummary(run)
    return !!run.error || digestSlackMessageUrl(run) !== null || !!headline || prs.length > 0
}
