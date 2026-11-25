import type { ResolvedUntilEnumApi } from '../generated/api.schemas'

export interface ResolveMode {
    value: ResolvedUntilEnumApi
    action: string
    description: string
}

// The issue page offers these in this order, so a plain resolve comes first.
export const RESOLVE_MODES: ResolveMode[] = [
    {
        value: 'next_occurrence',
        action: 'Resolve',
        description: 'Reopens the next time it happens.',
    },
    {
        value: 'new_release',
        action: 'Resolve in the next release',
        description: 'Reopens only if it happens again in a newer release.',
    },
]
