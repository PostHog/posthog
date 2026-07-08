import { useMountedLogic } from 'kea'

import { persistCreateToastLogic } from '../logics/persistCreateToastLogic'

/**
 * Keeps `persistCreateToastLogic` mounted for the calling surface's lifetime, so a foreground create
 * (`dashboard-create` / `create-feature-flag` / `survey-create`) toasts once it completes. Mount it from
 * every foreground surface (the same places that call `useForegroundStream`); the logic is global +
 * unkeyed, so double-mounting resolves to one instance with a single bus listener.
 */
export function usePersistCreateToasts(): void {
    useMountedLogic(persistCreateToastLogic)
}
