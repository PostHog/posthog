import type { SignalReportArtefact } from '../types'
import { reviewerExclusionAreas } from './reviewerExclusionAreas'

let nextId = 0
function artefact(type: string, content: Record<string, any>, createdAt: string): SignalReportArtefact {
    nextId += 1
    return { id: `artefact-${nextId}`, type, content, created_at: createdAt }
}

describe('reviewerExclusionAreas', () => {
    test.each([
        {
            name: 'no repository selection offers nothing',
            artefacts: [
                artefact('signal_finding', { signal_id: 's1', relevant_code_paths: ['billing/a.py'] }, '2026-10-01'),
            ],
            expected: [],
        },
        {
            name: 'normalized directories, most specific first, whole repository last',
            artefacts: [
                artefact('repo_selection', { repository: ' Acme/App ' }, '2026-10-01'),
                artefact(
                    'signal_finding',
                    {
                        signal_id: 's1',
                        relevant_code_paths: ['./billing/webhooks/retry.py', '/billing/webhooks/handler.py/'],
                    },
                    '2026-10-01'
                ),
            ],
            expected: [
                { repository: 'acme/app', pathPrefix: 'billing/webhooks' },
                { repository: 'acme/app', pathPrefix: 'billing' },
                { repository: 'acme/app', pathPrefix: '' },
            ],
        },
        {
            name: 'a superseded finding for the same signal is ignored',
            artefacts: [
                artefact('repo_selection', { repository: 'acme/app' }, '2026-10-01'),
                artefact(
                    'signal_finding',
                    { signal_id: 's1', relevant_code_paths: ['checkout/cart.py'] },
                    '2026-10-01'
                ),
                artefact(
                    'signal_finding',
                    { signal_id: 's1', relevant_code_paths: ['billing/invoice.py'] },
                    '2026-10-02'
                ),
            ],
            expected: [
                { repository: 'acme/app', pathPrefix: 'billing' },
                { repository: 'acme/app', pathPrefix: '' },
            ],
        },
    ])('$name', ({ artefacts, expected }) => {
        expect(reviewerExclusionAreas(artefacts)).toEqual(expected)
    })
})
