import type { ShortcutInput } from '@/api/shortcuts'
import { escapePath, shortcutMatchKey } from '@/model/adapters/viewPins'

// The phone writes exactly the row the web's `shortcutFromEntry` writes
// (`frontend/src/layout/panel-layout/ProjectTree/utils.tsx`), from the file-system entries in
// `products/dashboards/backend/models/dashboard.py` and `products/product_analytics/backend/models/insight.py`.
// The server dedupes a pin only on an exact match, and the web's star matches by `path` byte for byte, so any
// difference here leaves a duplicate row and an unstarred view on the web.

export type PinTarget =
    | {
          kind: 'dashboard'
          /** The numeric id. A demo dashboard has a text ref instead, which its demo pin keeps as the row's `ref`. */
          id: number | string
          name: string | null
      }
    | {
          kind: 'insight'
          shortId: string
          name: string | null
          derivedName?: string | null
          /** The insight's `query.kind`. A `BIVisualizationNode` lives under `/bi/`. */
          queryKind?: string | null
      }
    | { kind: 'web_analytics' }

export function shortcutInputFor(target: PinTarget): ShortcutInput {
    switch (target.kind) {
        case 'dashboard':
            return {
                path: escapePath(target.name || 'Untitled'),
                type: 'dashboard',
                ref: String(target.id),
                href: `/dashboard/${target.id}`,
            }
        case 'insight':
            return {
                path: escapePath(target.name || target.derivedName || 'Untitled'),
                type: 'insight',
                ref: target.shortId,
                href:
                    target.queryKind === 'BIVisualizationNode'
                        ? `/bi/${target.shortId}`
                        : `/insights/${target.shortId}`,
            }
        case 'web_analytics':
            return { path: 'Web analytics', type: 'web_analytics', ref: null, href: '/web' }
    }
}

/** The key that matches a target against pinned rows, whatever environment or name they carry. */
export function pinTargetKey(target: PinTarget): string {
    const input = shortcutInputFor(target)
    return shortcutMatchKey(input.type, input.ref)
}
