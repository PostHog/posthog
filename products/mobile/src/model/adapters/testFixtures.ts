import type { SignalReportApi } from '@/api/reports'

export function reportFixture(overrides: Partial<SignalReportApi> = {}): SignalReportApi {
    return {
        id: '00000000-0000-0000-0000-0000000000aa',
        title: 'Exports fail for guests',
        summary: 'Guests cannot export. It started Monday.',
        summary_lead: 'Guests cannot export.',
        status: 'ready',
        signal_count: 12,
        signals_at_run: 0,
        created_at: '2026-10-05T07:21:00Z',
        updated_at: '2026-10-09T09:00:00Z',
        metrics: [],
        charts: [],
        suggested_prompts: [],
        priority: 'P1',
        actionability: 'immediately_actionable',
        already_addressed: false,
        is_suggested_reviewer: true,
        source_products: ['error_tracking'],
        scout_name: null,
        implementation_pr_url: null,
        pull_requests: [],
        work_state: 'unclaimed',
        assignee: null,
        ...overrides,
    }
}
