import { DemoInvestigation } from './types'

/** The investigation whose full report the demo report pages render. */
export const DEMO_REPORT_ID = 'INV-0247'

/** Rotating activity phrases for live (still-investigating) rows. */
export const LIVE_ACTIVITY_PHRASES = [
    'querying error tracking…',
    'correlating with deploys…',
    'gathering session replays…',
    'estimating funnel impact…',
    'checking experiment interference…',
]

export const DEMO_INVESTIGATIONS: DemoInvestigation[] = [
    {
        id: 'INV-0247',
        headline: 'Checkout silently fails for returning users with expired saved cards',
        area: 'CHECKOUT',
        impact: '1,847 users',
        trend: 'up',
        impactWeight: 100,
        ageHours: 18,
        created: 'Aug 17, 16:12',
        status: 'New',
        unread: true,
        state: 'worsening',
        hasReport: true,
        verdict:
            'Returning users with expired saved cards hit a silent checkout failure: the server-side error is swallowed by the client. 1,847 users affected since the Aug 17 deploy.',
        proof: '214 session replays · 6 tickets',
        focus: {
            age: 'detected 18h ago',
            trendLabel: 'growing ~600/wk',
            actionLabel: 'Fix & monitor',
            flagKey: 'checkout_token_refresh_fallback',
            fixToast: 'Fix PR opening: web-checkout · fix/inv-0247 · monitoring armed',
            story: [
                {
                    label: 'PROBLEM',
                    body: 'When a returning customer pays with a saved card whose payment token has expired, the checkout request fails server-side, but the client swallows the error. No retry prompt, no message, no path forward except abandoning the purchase. Failures began 4 minutes after deploy a3f9c21 (Aug 14, 09:12 UTC).',
                },
                {
                    label: 'IMPACT',
                    body: '1,847 users in the last 72 hours, growing ~600/week. Returning-user payment conversion fell 84% → 72%. Estimated $38–52K weekly GMV at risk. 61% of affected sessions are iOS Safari; 31 accounts have >$1K lifetime spend.',
                },
                {
                    label: 'HOW WE KNOW',
                    body: 'First failure 4 minutes post-deploy; the diff removes the exact code path that handled this case. 99.8% failure rate for expired tokens vs 0.2–0.3% everywhere else. The client catch block discards the 402, and all 214 matching replays show no error UI.',
                },
                {
                    label: 'FIX · +4 LINES',
                    body: 'Restore the refresh fallback removed in a3f9c21. Strict validation is preserved for genuinely unrefreshable tokens. Mitigation available now: flip flag strict_token_validation off.',
                    code: "  if (token.expiresAt < Date.now()) {\n+   // Restore refresh fallback removed in a3f9c21 (INV-0247)\n+   const refreshed = await this.refreshToken(token);\n+   if (refreshed) return this.validate(refreshed);\n+   metrics.increment('payments.token_refresh_failed');\n    throw new TokenValidationError('TOKEN_EXPIRED');\n  }",
                },
            ],
        },
    },
    {
        id: 'INV-0251',
        headline: 'Latency spike in search autocomplete (p95 +740ms)',
        area: 'SEARCH',
        impact: 'p95 +740ms',
        trend: 'flat',
        impactWeight: 55,
        ageHours: 0.4,
        created: 'Aug 18, 09:48',
        status: 'Investigating',
        live: true,
        state: 'measuring',
        hasReport: false,
        verdict: 'Investigation in progress. Completed chapters are readable as they land.',
        proof: 'Watch the storyboard assemble in the live view',
    },
    {
        id: 'INV-0249',
        headline: 'Android app crashes on photo upload (OutOfMemoryError)',
        area: 'MOBILE · UPLOADS',
        impact: '412 users',
        trend: 'up',
        impactWeight: 80,
        ageHours: 26,
        created: 'Aug 17, 08:03',
        status: 'Assigned',
        state: 'worsening',
        hasReport: false,
        verdict:
            'Bitmap decoding of >12MP photos exceeds heap on devices with 4GB RAM or less after the image-picker upgrade in 8.3.0.',
        proof: 'assigned to K. Ito · Linear MOB-2214',
        focus: {
            age: 'detected 1d ago',
            trendLabel: 'growing',
            actionLabel: 'Fix & monitor',
            flagKey: 'android_upload_downsample',
            fixToast: 'Fix PR opening: mobile-android · fix/inv-0249 · monitoring armed',
            story: [
                {
                    label: 'PROBLEM',
                    body: 'The 8.3.0 image-picker upgrade decodes full-resolution bitmaps before upload. On devices with 4GB RAM or less, photos over ~12MP exceed the app heap and the process is killed.',
                },
                {
                    label: 'IMPACT',
                    body: '412 users in 24 hours, growing as the 8.3.0 rollout expands. Crash-free sessions on affected devices dropped 99.2% → 96.1%.',
                },
                {
                    label: 'HOW WE KNOW',
                    body: 'Every crash in the OOM group shares the same decode frame introduced in 8.3.0. 96% of occurrences are on devices with 4GB RAM or less; zero occurrences on 8.2.x.',
                },
                {
                    label: 'FIX',
                    body: 'Downsample before decode using inSampleSize computed from the target upload resolution: the pre-8.3.0 behavior, applied inside the new picker.',
                    code: '+ val opts = BitmapFactory.Options().apply {\n+   inSampleSize = calcSampleSize(src, MAX_UPLOAD_PX)\n+ }\n- val bmp = BitmapFactory.decodeStream(stream)\n+ val bmp = BitmapFactory.decodeStream(stream, null, opts)',
                },
            ],
        },
    },
    {
        id: 'INV-0244',
        headline: 'Signup conversion down 8% since pricing-page experiment started',
        area: 'GROWTH · SIGNUP',
        impact: '−8% signups',
        trend: 'flat',
        impactWeight: 70,
        ageHours: 49,
        created: 'Aug 16, 09:22',
        status: 'Viewed',
        state: 'holding',
        hasReport: true,
        verdict:
            "Leading hypothesis: variant B's delayed price reveal correlates with the drop. No code error found. Evidence is thin, so this is framed as a hypothesis, not a verdict.",
        proof: 'Medium confidence · thin-evidence report',
        focus: {
            age: 'detected 2d ago',
            trendLabel: 'stable',
            actionLabel: 'Pause variant B',
            fixToast: 'Variant B paused in experiment checkout-pricing-v2',
            story: [
                {
                    label: 'HYPOTHESIS',
                    body: 'The drop begins the same hour experiment checkout-pricing-v2 started, and is concentrated in variant B, which hides prices until account creation. Nothing else changed in the window.',
                },
                {
                    label: 'IMPACT',
                    body: 'Signup conversion down 8 points versus the trailing 28-day baseline. No errors, no crashes: a behavioral effect.',
                },
                {
                    label: 'WHY CONFIDENCE IS MEDIUM',
                    body: 'Two days of data; variant assignment is random but the sample is small. A holdback comparison would take one more week to reach significance.',
                },
                {
                    label: 'RECOMMENDED ACTION',
                    body: 'Pause variant B now, or accept one more week of data collection to confirm. The engine will re-run the analysis either way.',
                },
            ],
        },
    },
    {
        id: 'INV-0246',
        headline: 'Duplicate order events inflating revenue dashboards by ~3.2%',
        area: 'DATA · PIPELINE',
        impact: '3.2% dup events',
        trend: 'flat',
        impactWeight: 60,
        ageHours: 53,
        created: 'Aug 16, 05:47',
        status: 'Viewed',
        state: 'holding',
        hasReport: false,
        verdict:
            'Webhook consumer retries write a second order_completed event when the ack times out; dashboards double-count.',
        proof: 'DB dedup query · Kafka consumer logs',
        focus: {
            age: 'detected 2d ago',
            trendLabel: 'stable',
            actionLabel: 'Fix & monitor',
            flagKey: 'events_idempotent_writes',
            fixToast: 'Fix PR opening: events-pipeline · fix/inv-0246 · monitoring armed',
            story: [
                {
                    label: 'PROBLEM',
                    body: 'When the Kafka ack times out (p99 under load), the consumer retries and writes order_completed a second time with a new event id. Downstream dashboards count both.',
                },
                {
                    label: 'IMPACT',
                    body: 'Revenue dashboards over-report by ~3.2% on average, worse during traffic peaks. Orders and payments tables are correct.',
                },
                {
                    label: 'HOW WE KNOW',
                    body: 'A dedup query on (order_id, event_type) finds 3.2% duplicates, all within 30s of an ack-timeout log line on the consumer.',
                },
                {
                    label: 'FIX',
                    body: 'Write events with an idempotency key derived from order_id + event_type so retries upsert instead of insert. A backfill script is included for the affected window.',
                },
            ],
        },
    },
    {
        id: 'INV-0250',
        headline: 'iOS push opt-in prompt shown twice on first launch',
        area: 'MOBILE · ONBOARDING',
        impact: '96 users',
        trend: 'up',
        impactWeight: 30,
        ageHours: 6,
        created: 'Aug 18, 04:15',
        status: 'New',
        unread: true,
        state: 'worsening',
        hasReport: false,
        verdict: 'Race between the onboarding coordinator and the notification manager, both scheduling the prompt.',
        proof: '31 replays · no revenue impact identified',
        focus: {
            age: 'detected 6h ago',
            trendLabel: 'growing',
            actionLabel: 'Fix & monitor',
            flagKey: 'ios_prompt_single_owner',
            fixToast: 'Fix PR opening: mobile-ios · fix/inv-0250 · monitoring armed',
            story: [
                {
                    label: 'PROBLEM',
                    body: 'On first launch, the onboarding coordinator schedules the push opt-in prompt, and the notification manager independently schedules it again on foreground. Users see the system dialog twice.',
                },
                {
                    label: 'IMPACT',
                    body: '96 users so far. Annoyance, not breakage, but double-prompting measurably lowers opt-in acceptance.',
                },
                {
                    label: 'FIX',
                    body: 'Route all prompt scheduling through the notification manager and have onboarding request it, not schedule it. One flag, one owner.',
                },
            ],
        },
    },
    {
        id: 'INV-0238',
        headline: 'Password reset emails delayed up to 40 minutes',
        area: 'AUTH · EMAIL',
        impact: '289 users',
        trend: 'down',
        impactWeight: 45,
        ageHours: 120,
        created: 'Aug 13, 10:31',
        status: 'Verifying',
        state: 'recovering',
        hasReport: false,
        verdict: 'Fix shipped. The engine is watching delivery latency for 7 days before marking this resolved.',
        proof: 'p95 delivery now 38s (was 24m)',
        focus: {
            age: 'fix shipped 8h ago',
            trendLabel: 'declining',
            actionLabel: 'View verification',
            fixToast: 'Verification dashboard opened: 7-day watch, day 1 of 7',
            story: [
                {
                    label: 'WHAT HAPPENED',
                    body: 'A misconfigured retry queue serialized transactional email sends behind marketing batches. Reset emails waited up to 40 minutes at peak.',
                },
                {
                    label: 'FIX SHIPPED',
                    body: 'Transactional sends moved to a dedicated priority queue. Shipped 8h ago.',
                },
                {
                    label: 'VERIFICATION PLAN',
                    body: 'The engine watches p95 delivery latency for 7 days. Pass criteria: p95 under 60s, zero new matching tickets. A resolution epilogue will be appended automatically.',
                },
            ],
        },
    },
    {
        id: 'INV-0231',
        headline: 'Checkout crash on address autofill (undefined postal code)',
        area: 'CHECKOUT',
        impact: '0 in 7 days',
        trend: 'down',
        impactWeight: 20,
        ageHours: 220,
        created: 'Aug 9, 06:20',
        status: 'Resolved',
        state: 'resolved',
        hasReport: false,
        verdict:
            'Error rate returned to baseline; 0 occurrences in 7 days. 1,204 users recovered. An epilogue was appended to the report.',
        proof: 'closing stat verified against error tracking + funnel',
    },
    {
        id: 'INV-0240',
        headline: 'Cart abandonment spike on Friday evenings',
        area: 'CHECKOUT',
        impact: 'disputed',
        trend: 'flat',
        impactWeight: 15,
        ageHours: 96,
        created: 'Aug 14, 10:12',
        status: 'Disputed',
        state: 'disputed',
        hasReport: false,
        verdict:
            'Marked disputed by J. Reyes (wrong root cause: the spike matches a weekly marketing email, not a defect). The engine is re-investigating with this correction.',
        proof: 'dispute registered · re-investigation queued',
    },
    {
        id: 'INV-0236',
        headline: 'Webhook retry storm to partner inventory API',
        area: 'INTEGRATIONS',
        impact: '0 users',
        trend: 'flat',
        impactWeight: 10,
        ageHours: 150,
        created: 'Aug 12, 04:33',
        status: 'Dismissed',
        state: 'dismissed',
        hasReport: false,
        verdict:
            "Dismissed: known and accepted behavior. Retries are within the partner's rate contract. Kept for audit.",
        proof: 'dismissed by M. Okafor with reason',
    },
]

/** Investigations that appear in focus mode, in triage order. */
export const FOCUS_INVESTIGATIONS: DemoInvestigation[] = DEMO_INVESTIGATIONS.filter((inv) => inv.focus)

export function getDemoInvestigation(id: string): DemoInvestigation | null {
    return DEMO_INVESTIGATIONS.find((inv) => inv.id === id) ?? null
}
