import { useActions, useValues } from 'kea'

import { LLMTracePerson } from '~/queries/schema/schema-general'

import { llmPersonsLazyLoaderLogic } from '../llmPersonsLazyLoaderLogic'

export interface UsePersonDataResult {
    person: LLMTracePerson | null
    isLoading: boolean
}

export function usePersonData(distinctId: string | undefined): UsePersonDataResult {
    const { personsCache, isDistinctIdLoading } = useValues(llmPersonsLazyLoaderLogic)
    const { ensurePersonLoaded } = useActions(llmPersonsLazyLoaderLogic)

    if (!distinctId) {
        return { person: null, isLoading: false }
    }

    const cached = personsCache[distinctId]
    const loading = isDistinctIdLoading(distinctId)

    if (cached === undefined && !loading) {
        ensurePersonLoaded(distinctId)
    }

    return {
        person: cached ?? null,
        isLoading: loading || cached === undefined,
    }
}
