import { useValues } from 'kea'
import type { ReactNode } from 'react'

import { WorkflowSuggestionAvailabilityContext } from 'products/posthog_ai/frontend/api/runner'

import { workflowAiAvailabilityLogic } from './workflowAiAvailabilityLogic'

export function WorkflowSuggestionProvider({ children }: { children: ReactNode }): JSX.Element {
    const { aiFirstNewEnabled } = useValues(workflowAiAvailabilityLogic)

    return (
        <WorkflowSuggestionAvailabilityContext.Provider value={aiFirstNewEnabled}>
            {children}
        </WorkflowSuggestionAvailabilityContext.Provider>
    )
}
