// Whether the tab has lenses to show. Lens rows exist only for projects in the impact preview, so a list that
// loaded without any is a project the backend does not compute lenses for.
export type ImpactTabStatus = 'loading' | 'error' | 'off' | 'ready'

// What the open view can say about its items. "Empty" is a verdict, so it needs every lens in the view calculated.
export type ImpactViewStatus = 'calculating' | 'not_calculated' | 'unavailable' | 'empty' | 'ready'

export interface ImpactLensProgress {
    computing: boolean
    calculated: boolean
    evaluable: boolean
}

export function impactTabStatus({
    lensCount,
    loading,
    loadFailed,
}: {
    lensCount: number
    loading: boolean
    loadFailed: boolean
}): ImpactTabStatus {
    if (lensCount > 0) {
        return 'ready'
    }
    if (loading) {
        return 'loading'
    }
    return loadFailed ? 'error' : 'off'
}

export function impactViewStatus(lenses: ImpactLensProgress[], itemCount: number): ImpactViewStatus {
    if (itemCount > 0) {
        return 'ready'
    }
    const uncalculated = lenses.filter((lens) => !lens.calculated)
    if (uncalculated.length > 0) {
        return uncalculated.some((lens) => lens.computing) ? 'calculating' : 'not_calculated'
    }
    if (lenses.length > 0 && lenses.every((lens) => !lens.evaluable)) {
        return 'unavailable'
    }
    return 'empty'
}
