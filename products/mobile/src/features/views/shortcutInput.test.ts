import type { ShortcutInput } from '@/api/shortcuts'
import { shortcutName } from '@/model/adapters/viewPins'

import { type PinTarget, shortcutInputFor } from './shortcutInput'

describe('shortcutInputFor', () => {
    test.each<[string, PinTarget, ShortcutInput]>([
        [
            'a dashboard with a slash in its name',
            { kind: 'dashboard', id: 12, name: 'Growth / weekly' },
            { path: 'Growth \\/ weekly', type: 'dashboard', ref: '12', href: '/dashboard/12' },
        ],
        [
            'an unnamed dashboard',
            { kind: 'dashboard', id: 3, name: '' },
            { path: 'Untitled', type: 'dashboard', ref: '3', href: '/dashboard/3' },
        ],
        [
            'an insight named only by the server, with a backslash',
            { kind: 'insight', shortId: 'aB3dE9', name: null, derivedName: 'Pageview count \\ day' },
            { path: 'Pageview count \\\\ day', type: 'insight', ref: 'aB3dE9', href: '/insights/aB3dE9' },
        ],
        [
            'a BI insight',
            { kind: 'insight', shortId: 'xY12', name: 'Revenue', queryKind: 'BIVisualizationNode' },
            { path: 'Revenue', type: 'insight', ref: 'xY12', href: '/bi/xY12' },
        ],
        [
            'web analytics',
            { kind: 'web_analytics' },
            { path: 'Web analytics', type: 'web_analytics', ref: null, href: '/web' },
        ],
    ])('writes the web row for %s', (_name, target, expected) => {
        const input = shortcutInputFor(target)

        expect(input).toEqual(expected)
        if (target.kind !== 'web_analytics') {
            expect(shortcutName(input.path)).toBe(
                target.name || ('derivedName' in target && target.derivedName) || 'Untitled'
            )
        }
    })
})
