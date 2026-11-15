import { mergeOverlapping } from './releaseTracks'
import { ReleaseSpan } from './releaseUtils'

const span = (key: string, kind: ReleaseSpan['kind'], from: string, to: string, label: string): ReleaseSpan => ({
    key,
    kind,
    from,
    to,
    label,
    href: `/${key}`,
})

describe('mergeOverlapping', () => {
    it('merges overlapping experiments but keeps early access on its own', () => {
        const merged = mergeOverlapping([
            span('ea', 'early_access', '2026-11-01', '2026-11-12', 'Early access, beta'),
            span('exp-1', 'experiment', '2026-11-03', '2026-11-12', 'Experiment, day 9'),
            span('exp-2', 'experiment', '2026-11-05', '2026-11-12', 'Experiment, day 7'),
        ])
        expect(merged.map(({ href, label }) => [href, label])).toEqual([
            ['/ea', 'Early access, beta'],
            ['/exp-1', '2 experiments'],
        ])
    })
})
