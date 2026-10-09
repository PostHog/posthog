import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { WorkflowSuggestionAvailabilityContext } from 'products/posthog_ai/frontend/api/runner'

import { newWorkflowLogic } from './newWorkflowLogic'

export function WorkflowSuggestionProvider({ children }: { children: ReactNode }): JSX.Element {
    const { aiFirstNewEnabled } = useValues(newWorkflowLogic)

    return (
        <WorkflowSuggestionAvailabilityContext.Provider value={aiFirstNewEnabled}>
            {children}
        </WorkflowSuggestionAvailabilityContext.Provider>
    )
}
