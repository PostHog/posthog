import type { ResolvedUntilEnumApi } from '../generated/api.schemas'

export interface ResolveMode {
    value: ResolvedUntilEnumApi
    action: string
    description: string
}

// The issue page offers these in this order, so a plain resolve comes first.
export const RESOLVE_MODES: ResolveMode[] = [
    {
        value: 'new_release',
        action: 'Resolve',
        description: 'Reopens only if it happens again in a newer release.',
    },
    {
        value: 'next_occurrence',
        action: 'Resolve until next occurrence',
        description: 'Reopens the next time it happens, even in an existing release.',
    },
]
