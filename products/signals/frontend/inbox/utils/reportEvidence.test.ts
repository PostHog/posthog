import type { SignalNodeApi } from 'products/signals/frontend/generated/api.schemas'

import { mockSignals } from '../__mocks__/inboxMocks'
import { citedReportEvidence, selectReportEvidence } from './reportEvidence'

describe('report evidence', () => {
    const signals = mockSignals('report')
    const projectUrl = 'https://us.posthog.com/project/2'

    it('previews distinct sources and leaves repeated signals available in the full list', () => {
        const repeated = { ...signals[0], signal_id: 'repeat', timestamp: '2026-06-12T12:00:00Z' }
        const all = [signals[0], repeated, ...signals.slice(1)]
        expect(selectReportEvidence(all).map((signal) => signal.signal_id)).toEqual([
            'repeat',
            signals[1].signal_id,
            signals[3].signal_id,
        ])
        expect(all).toHaveLength(5)
    })

    it('deduplicates alert emissions but keeps unrelated evidence without source ids', () => {
        const alert: SignalNodeApi = {
            ...signals[0],
            source_product: 'analytics',
            extra: {
                alert_id: 'alert-1',
                alert_name: 'Error alert',
                alert_check_id: 'check-1',
                insight_id: 'insight-1',
                detector_type: 'z_score',
                verdict: 'true_positive',
                url: '/alerts/alert-1',
            },
        }
        const all: SignalNodeApi[] = [alert, { ...alert, source_id: 'another-emission', signal_id: 'repeat' }]
        expect(selectReportEvidence(all)).toHaveLength(1)
        expect(selectReportEvidence(signals.slice(0, 2).map((signal) => ({ ...signal, source_id: '' })))).toHaveLength(
            2
        )
    })

    it.each([
        '[Errors](/project/2/error_tracking/report-src-0)',
        '[Errors](https://us.posthog.com/project/2/error_tracking/report-src-0)',
        '[Errors](/project/2/error_tracking/report-src-0?fingerprint=abc)',
        '[Replay](/project/2/replay/report-src-1?t=12)',
        '[Errors][source]\n\n[source]: /project/2/error_tracking/report-src-0',
    ])('finds evidence explicitly linked by the text: %s', (markdown) => {
        expect(citedReportEvidence(markdown, signals, projectUrl)).toEqual([
            signals[markdown.includes('/replay/') ? 1 : 0],
        ])
    })

    it.each([
        '[Other project](/project/3/error_tracking/report-src-0)',
        '[Other host](https://other.example/project/2/error_tracking/report-src-0)',
        '`[Errors](/project/2/error_tracking/report-src-0)`',
        '[Unused definition]\n\n[source]: /project/2/error_tracking/report-src-0',
        'The report mentions report-src-0 without a source link.',
    ])('does not infer a citation from %s', (markdown) => {
        expect(citedReportEvidence(markdown, signals, projectUrl)).toEqual([])
    })

    it('shows the newest evidence when a cited source emitted several signals', () => {
        const repeated = { ...signals[0], signal_id: 'repeat', timestamp: '2026-06-12T12:00:00Z' }
        expect(
            citedReportEvidence('[Errors](/error_tracking/report-src-0)', [...signals, repeated], projectUrl)
        ).toEqual([repeated])
    })
})
