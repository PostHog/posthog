import { useActions, useValues } from 'kea'
import { useContext, useEffect } from 'react'

import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import {
    PreviewTrigger,
    emailPreviewPersonLogic,
} from 'scenes/hog-functions/email-templater/preview/emailPreviewPersonLogic'
import { EmailPreviewScopeContext } from 'scenes/hog-functions/email-templater/preview/EmailPreviewScopeContext'

import { AnyPropertyFilter } from '~/types'

import { workflowLogic } from '../../../workflowLogic'
import type { HogFlow } from '../../types'
import { CanvasPreviewPersonContext } from './CanvasPreviewPersonContext'
import { asRecord, asText } from './stepValues'

// Previews read the event that would have started the run, so the first trigger event or action, with the filters
// it must pass, stands in for it. Saved filters carry compiled bytecode, which a query refuses.
function previewTrigger(trigger: HogFlow['trigger']): PreviewTrigger | null {
    if (trigger?.type !== 'event') {
        return null
    }
    const filters = asRecord(trigger.filters)
    const [event] = Array.isArray(filters.events) ? filters.events : []
    const [action] = Array.isArray(filters.actions) ? filters.actions : []
    // A trigger with only property filters matches any event that passes them.
    const entity = asRecord(event ?? action)
    const properties = [
        ...(Array.isArray(filters.properties) ? filters.properties : []),
        ...(Array.isArray(entity.properties) ? entity.properties : []),
    ].map((filter) => {
        const { bytecode: _bytecode, conditionHash: _conditionHash, ...rest } = asRecord(filter)
        return rest as AnyPropertyFilter
    })
    // An empty draft trigger starts nothing, but one with only property filters matches any event that passes them.
    if (!event && !action && properties.length === 0) {
        return null
    }
    return {
        // "All events" carries a null id and a display name, so match on the id.
        event: event ? (asText(entity.id) ?? null) : null,
        actionId: action && !event ? Number(entity.id) : undefined,
        properties,
        filterTestAccounts: !!filters.filter_test_accounts,
    }
}

function PreviewPersonScope({ children }: { children: React.ReactNode }): JSX.Element {
    const scope = useContext(EmailPreviewScopeContext)
    const { previewPerson } = useValues(emailPreviewPersonLogic({ scope }))
    const { setTrigger } = useActions(emailPreviewPersonLogic({ scope }))
    const { workflow } = useValues(workflowLogic)
    const trigger = previewTrigger(workflow.trigger)
    const triggerKey = JSON.stringify(trigger)

    useEffect(() => {
        setTrigger(trigger)
        // The key stands in for the trigger, which is a new object on every render.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [setTrigger, triggerKey])

    return <CanvasPreviewPersonContext.Provider value={previewPerson}>{children}</CanvasPreviewPersonContext.Provider>
}

/** Renders the canvas's email steps as the workflow's preview person, while person previews are on. */
export function CanvasPreviewPersonProvider({ children }: { children: React.ReactNode }): JSX.Element {
    const enabled = useFeatureFlag('WORKFLOWS_EMAIL_PERSON_PREVIEW')
    return enabled ? <PreviewPersonScope>{children}</PreviewPersonScope> : <>{children}</>
}
