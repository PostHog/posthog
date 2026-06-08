import { actions, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { urls } from 'scenes/urls'

import { PulseScanConfig } from '~/queries/schema/schema-general'

import type { pulseLogicType } from './pulseLogicType'
import {
    PulseDigestDetail,
    PulseDigestSummary,
    PulseFindingType,
    PulseSubscriptionType,
    PulseWatchedCandidate,
} from './pulseTypes'

const SCAN_POLL_INTERVAL_MS = 3000
const SCAN_POLL_ATTEMPTS = 40 // ~2 minutes — covers a slow scan plus digest synthesis

// The event Pulse emits per finding into the team's own project — the trigger a CDP destination filters on.
const PULSE_FINDING_EVENT = 'pulse_finding_surfaced'

// A Pulse-shaped Slack message prefilled into the destination. The generic template assumes a person
// triggered the event, but Pulse's distinct_id is the digest, not a user — so we lead with the metric +
// the human-readable narrative (the raw numeric props aren't formatted) and link back to the digest.
// {project.url}/{event.properties.*} are resolved by the CDP destination at send time; source_url is a
// relative path so it's prefixed with {project.url} for an absolute link.
const PULSE_SLACK_BLOCKS = [
    {
        type: 'header',
        text: { type: 'plain_text', text: '📈 Pulse: {event.properties.metric}' },
    },
    {
        type: 'section',
        text: { type: 'mrkdwn', text: '{event.properties.narrative}' },
    },
    {
        type: 'context',
        elements: [{ type: 'mrkdwn', text: 'Flagged by PostHog Pulse · <{project.url}|{project.name}>' }],
    },
    {
        type: 'actions',
        elements: [
            {
                type: 'button',
                url: '{project.url}{event.properties.source_url}',
                text: { type: 'plain_text', text: 'Open in Pulse' },
            },
        ],
    },
]
const PULSE_SLACK_TEXT = 'Pulse flagged {event.properties.metric}: {event.properties.narrative}'

const DEFAULT_SUBSCRIPTION: PulseSubscriptionType = {
    id: null,
    enabled: false,
    frequency: 'weekly',
    detection_mode: 'change_v1',
    sensitivity: 'balanced',
    min_change_pct: 0.25,
    baseline_weeks: 4,
    max_findings: 5,
    robust_z_threshold: 3.5,
    last_scan_at: null,
    next_scan_at: null,
    created_at: null,
}

// Defaults mirror the backend PulseScanConfig (the production constants). The staff tuning draft starts
// here and is persisted to localStorage so tweaks survive a reload while iterating.
export const PULSE_SCAN_CONFIG_DEFAULTS: PulseScanConfig = {
    max_candidates: 200,
    recent_days: 30,
    min_viewers_for_recent_insight: 3,
    dashboard_tile_limit: 10,
    recent_insight_limit: 100,
    saved_insight_limit: 15,
    top_event_limit: 25,
    min_baseline_value: 5,
    min_change_pct: 0.25,
    robust_z_threshold: 3.5,
    baseline_weeks: 4,
    max_findings: 5,
}

export const pulseLogic = kea<pulseLogicType>([
    path(['scenes', 'pulse', 'pulseLogic']),
    actions({
        loadDigests: true,
        loadMoreDigests: true,
        loadFindings: (digestId?: string) => ({ digestId }),
        loadSubscription: true,
        loadWatched: true,
        getDigest: (id: string) => ({ id }),
        setExpandedDigestId: (id: string | null) => ({ id }),
        setDigestsNext: (next: string | null) => ({ next }),
        updateSubscriptionLocal: (patch: Partial<PulseSubscriptionType>) => ({ patch }),
        saveSubscription: true,
        pollScan: true,
        markScanInProgress: true,
        scanResolved: true,
        setUpPulseAlerts: true,
        updateScanConfigLocal: (patch: Partial<PulseScanConfig>) => ({ patch }),
        resetScanConfig: true,
    }),
    loaders(({ values, cache }) => ({
        digests: [
            [] as PulseDigestSummary[],
            {
                loadDigests: async () => {
                    const response = await api.pulse.listDigests()
                    // Stash the cursor in cache; the success listener moves it into the reducer, keeping
                    // loaders free of action dispatches (a kea anti-pattern that can race).
                    cache.digestsNext = response.next ?? null
                    return response.results || []
                },
                loadMoreDigests: async () => {
                    const next = values.digestsNext
                    if (!next) {
                        return values.digests
                    }
                    const response = await api.pulse.listDigests(next)
                    cache.digestsNext = response.next ?? null
                    return [...values.digests, ...(response.results || [])]
                },
            },
        ],
        expandedDigest: [
            null as PulseDigestDetail | null,
            {
                getDigest: async ({ id }) => await api.pulse.getDigest(id),
            },
        ],
        findings: [
            [] as PulseFindingType[],
            {
                loadFindings: async ({ digestId }) => {
                    // Default to the latest digest so its findings are never truncated by older digests'
                    // findings under the shared rank-ordered pagination. On mount the digests haven't
                    // loaded yet — skip the unfiltered all-digests fetch; loadDigestsSuccess re-issues
                    // this with the latest digest id.
                    const id = digestId ?? values.latestDigest?.id
                    if (!id) {
                        return []
                    }
                    const response = await api.pulse.listFindings(id)
                    return response.results || []
                },
            },
        ],
        subscription: [
            null as PulseSubscriptionType | null,
            {
                loadSubscription: async () => await api.pulse.currentSubscription(),
                saveSubscription: async () => {
                    const draft = values.subscriptionDraft
                    if (!draft) {
                        return null
                    }
                    const payload: Partial<PulseSubscriptionType> = {
                        enabled: draft.enabled,
                        frequency: draft.frequency,
                        detection_mode: draft.detection_mode,
                        sensitivity: draft.sensitivity,
                        min_change_pct: draft.min_change_pct,
                        baseline_weeks: draft.baseline_weeks,
                        max_findings: draft.max_findings,
                        robust_z_threshold: draft.robust_z_threshold,
                    }
                    if (draft.id) {
                        return await api.pulse.updateSubscription(draft.id, payload)
                    }
                    return await api.pulse.createSubscription(payload)
                },
            },
        ],
        watchedCandidates: [
            [] as PulseWatchedCandidate[],
            {
                loadWatched: async () => {
                    const response = await api.pulse.watchedCandidates()
                    return response.results || []
                },
            },
        ],
        scanTrigger: [
            null as { workflow_id: string } | null,
            {
                triggerScan: async (config?: Partial<PulseScanConfig>) => await api.pulse.triggerScan(config),
            },
        ],
    })),
    reducers({
        expandedDigestId: [
            null as string | null,
            {
                setExpandedDigestId: (_, { id }) => id,
            },
        ],
        // DRF `next` cursor for older digests — drives the "Load more" button when there are more pages.
        digestsNext: [
            null as string | null,
            {
                setDigestsNext: (_, { next }) => next,
            },
        ],
        // Separate from `digestsLoading` so appending a page never blanks the list into a skeleton.
        loadingMore: [
            false,
            {
                loadMoreDigests: () => true,
                loadMoreDigestsSuccess: () => false,
                loadMoreDigestsFailure: () => false,
            },
        ],
        subscriptionDraft: [
            null as PulseSubscriptionType | null,
            {
                loadSubscriptionSuccess: (_, { subscription }) => subscription,
                saveSubscriptionSuccess: (_, { subscription }) => subscription,
                updateSubscriptionLocal: (state, { patch }) =>
                    state ? { ...state, ...patch } : { ...DEFAULT_SUBSCRIPTION, ...patch },
            },
        ],
        digestsError: [
            false,
            {
                loadDigests: () => false,
                loadDigestsSuccess: () => false,
                loadDigestsFailure: () => true,
            },
        ],
        findingsError: [
            false,
            {
                loadFindings: () => false,
                loadFindingsSuccess: () => false,
                loadFindingsFailure: () => true,
            },
        ],
        subscriptionError: [
            false,
            {
                loadSubscription: () => false,
                loadSubscriptionSuccess: () => false,
                loadSubscriptionFailure: () => true,
            },
        ],
        watchedError: [
            false,
            {
                loadWatched: () => false,
                loadWatchedSuccess: () => false,
                loadWatchedFailure: () => true,
            },
        ],
        isScanInProgress: [
            false,
            {
                triggerScanSuccess: () => true,
                triggerScanFailure: () => false,
                markScanInProgress: () => true,
                scanResolved: () => false,
                // A poll-time digests failure breaks the loadDigestsSuccess poll loop, so clear the
                // spinner here — the digestsError banner surfaces the error and a retry separately.
                loadDigestsFailure: () => false,
            },
        ],
        // Staff scan-tuning draft. Persisted to localStorage so iterating on the knobs survives reloads;
        // never sent anywhere until a "Run scan with these settings" trigger fires.
        scanConfigDraft: [
            PULSE_SCAN_CONFIG_DEFAULTS,
            { persist: true },
            {
                updateScanConfigLocal: (state, { patch }) => ({ ...state, ...patch }),
                resetScanConfig: () => PULSE_SCAN_CONFIG_DEFAULTS,
            },
        ],
    }),
    listeners(({ actions, values, cache }) => ({
        saveSubscriptionSuccess: () => {
            lemonToast.success('Pulse settings saved')
        },
        saveSubscriptionFailure: () => {
            lemonToast.error('Failed to save Pulse settings')
        },
        setUpPulseAlerts: () => {
            // Deep-link into the CDP destination form pre-filtered to Pulse finding events, so the user only
            // has to pick a Slack channel and save. hogFunctionConfigurationLogic reads `configuration` from
            // the URL hash and merges it into the form (same seam the "duplicate destination" flow uses).
            router.actions.push(
                urls.hogFunctionNew('template-slack'),
                {},
                {
                    configuration: {
                        name: 'Pulse findings → Slack',
                        filters: {
                            events: [{ id: PULSE_FINDING_EVENT, name: PULSE_FINDING_EVENT, type: 'events' }],
                        },
                        // The form's input schema comes from the template; these prefill the message (the merge
                        // is shallow, so we include icon/username too). The user still picks workspace + channel.
                        inputs: {
                            icon_emoji: { value: ':chart_with_upwards_trend:' },
                            username: { value: 'PostHog Pulse' },
                            blocks: { value: PULSE_SLACK_BLOCKS },
                            text: { value: PULSE_SLACK_TEXT },
                        },
                    },
                }
            )
        },
        triggerScan: () => {
            // Remember the current digest so we can tell when a *new* one finishes (the scan creates a
            // fresh digest), and budget a bounded number of polls so we don't loop forever.
            cache.preScanDigestId = values.latestDigest?.id ?? null
            cache.scanPollsLeft = SCAN_POLL_ATTEMPTS
        },
        triggerScanSuccess: () => {
            lemonToast.success('Pulse scan started — findings will appear here shortly.')
            actions.pollScan()
        },
        triggerScanFailure: () => {
            lemonToast.error('Failed to start Pulse scan.')
        },
        pollScan: async (_, breakpoint) => {
            await breakpoint(SCAN_POLL_INTERVAL_MS)
            // Refetches page 1 (where a new digest lands). If the user had paged into older digests via
            // "Load more", that resets to the newest page — acceptable: a scan finishing should surface
            // its fresh result at the top, and digests accrue weekly so paging is rarely in flight.
            // loadDigestsSuccess re-loads the findings for the (possibly new) latest digest.
            actions.loadDigests()
        },
        loadMoreDigestsSuccess: () => {
            actions.setDigestsNext(cache.digestsNext ?? null)
        },
        loadDigestsSuccess: ({ digests }) => {
            actions.setDigestsNext(cache.digestsNext ?? null)
            const latest = digests[0]
            if (latest) {
                // Refresh findings scoped to the new latest digest (a poll may have produced one).
                actions.loadFindings(latest.id)
            }
            const isGenerating = !!latest && (latest.status === 'pending' || latest.status === 'generating')
            if (values.isScanInProgress) {
                cache.scanPollsLeft = (cache.scanPollsLeft ?? 0) - 1
                // Done once a *new* digest (different from the one present at trigger time) has settled,
                // i.e. findings AND the summary are ready — or once the poll budget runs out.
                const newDigestSettled =
                    !!latest &&
                    latest.id !== cache.preScanDigestId &&
                    (latest.status === 'delivered' || latest.status === 'failed')
                if (newDigestSettled || cache.scanPollsLeft <= 0) {
                    actions.scanResolved()
                } else {
                    actions.pollScan()
                }
            } else if (isGenerating) {
                // A scan we didn't trigger here (e.g. scheduled) is mid-flight — reflect it and poll.
                cache.preScanDigestId = null
                cache.scanPollsLeft = SCAN_POLL_ATTEMPTS
                actions.markScanInProgress()
                actions.pollScan()
            }
        },
    })),
    selectors({
        latestDigest: [
            (s) => [s.digests],
            (digests): PulseDigestSummary | null => (digests.length ? digests[0] : null),
        ],
        shouldShowEmptyState: [
            (s) => [s.digests, s.digestsLoading],
            (digests, digestsLoading): boolean => !digestsLoading && digests.length === 0,
        ],
        findingsForLatest: [
            (s) => [s.findings, s.latestDigest],
            (findings, latestDigest): PulseFindingType[] =>
                latestDigest ? findings.filter((f) => f.digest === latestDigest.id) : [],
        ],
    }),
])
