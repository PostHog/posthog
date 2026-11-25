import type { ResolvedUntilEnumApi } from '../generated/api.schemas'

export interface ResolveMode {
    value: ResolvedUntilEnumApi
    action: string
}

// The issue page offers these in this order, so a plain resolve comes first.
export const RESOLVE_MODES: ResolveMode[] = [
    { value: 'next_occurrence', action: 'Resolve' },
    { value: 'new_release', action: 'Resolve in the next release' },
]
