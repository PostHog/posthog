import { InvestigationDocument, newInvestigation } from './investigationDocument'

export function investigationExample(): InvestigationDocument {
    return {
        ...newInvestigation('Why did trial conversion fall after the onboarding release?'),
        example: true,
        status: 'review',
        context:
            'Example: compare two fully matured weekly signup cohorts with a 7-day conversion window. Exclude internal and test accounts. All numbers and explanations in this example are invented.',
        checks: ['definition', 'maturity', 'tracking'],
        nextEvidenceNumber: 3,
        evidence: [
            {
                id: 'conversion',
                reference: 1,
                title: 'Trial conversion rate (%)',
                kind: 'query',
                sql: 'SELECT 18.4 AS conversion_rate',
                url: '',
                note: 'The example conversion rate fell from 24% to 18.4%. Check acquisition mix before attributing the change to onboarding.',
            },
            {
                id: 'segments',
                reference: 2,
                title: 'Conversion by acquisition channel',
                kind: 'query',
                sql: "SELECT 'Organic' AS channel, 240 AS trials, 60 AS converted UNION ALL SELECT 'Paid', 360, 50 ORDER BY channel",
                url: '',
                note: 'Paid traffic accounts for a larger share of the example cohort. These counts alone do not isolate a release effect.',
            },
        ],
        hypotheses: [
            {
                id: 'mix',
                title: 'The acquisition mix shifted toward lower-converting traffic',
                status: 'supported',
                reasoning:
                    'E2 is consistent with a composition effect. Compare conversion within each channel across both periods before estimating how much it explains.',
                evidenceIds: ['segments'],
            },
            {
                id: 'release',
                title: 'The new onboarding flow reduced conversion',
                status: 'open',
                reasoning:
                    'The release coincided with the drop, but timing alone is insufficient. Compare exposure groups and review the affected sessions.',
                evidenceIds: ['conversion'],
            },
            {
                id: 'tracking',
                title: 'The conversion event stopped firing',
                status: 'ruled_out',
                reasoning:
                    'In this invented scenario, the event volume reconciles with billing records. For a real investigation, attach the reconciliation query.',
                evidenceIds: ['conversion'],
            },
        ],
        conclusion:
            'Trial conversion is lower in the latest example cohort (E1). A shift toward paid acquisition is a plausible contributor (E2), but the current evidence does not establish whether the onboarding release caused the drop.',
        decision:
            'Compare matched acquisition segments before changing onboarding. Add an experiment or release link as evidence and have a teammate review the population assumptions.',
        followUp:
            'Review after the next cohort has completed its 7-day window. Rerun the same query definitions and revisit the conclusion if within-channel conversion also falls.',
        baselineId: 'baseline',
        runs: [
            {
                id: 'baseline',
                at: '2026-11-02T12:00:00.000Z',
                conclusion: '',
                results: [
                    {
                        evidenceId: 'conversion',
                        title: 'Trial conversion rate (%)',
                        sql: 'SELECT 18.4 AS conversion_rate',
                        columns: ['conversion_rate'],
                        rows: [[24]],
                        truncated: false,
                        error: null,
                    },
                ],
            },
            {
                id: 'latest',
                at: '2026-11-09T12:00:00.000Z',
                conclusion: 'The change needs a segment-level review.',
                results: [
                    {
                        evidenceId: 'conversion',
                        title: 'Trial conversion rate (%)',
                        sql: 'SELECT 18.4 AS conversion_rate',
                        columns: ['conversion_rate'],
                        rows: [[18.4]],
                        truncated: false,
                        error: null,
                    },
                    {
                        evidenceId: 'segments',
                        title: 'Conversion by acquisition channel',
                        sql: "SELECT 'Organic' AS channel, 240 AS trials, 60 AS converted UNION ALL SELECT 'Paid', 360, 50 ORDER BY channel",
                        columns: ['channel', 'trials', 'converted'],
                        rows: [
                            ['Organic', 240, 60],
                            ['Paid', 360, 50],
                        ],
                        truncated: false,
                        error: null,
                    },
                ],
            },
        ],
    }
}
