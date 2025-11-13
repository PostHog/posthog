import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventProperties } from 'lib/components/Errors/types'

import { exceptionCardLogic } from '../../components/ExceptionCard/exceptionCardLogic'
import javascript_empty from './javascript_empty.json'
import javascript_resolved from './javascript_resolved.json'
import javascript_unresolved from './javascript_unresolved.json'
import node_unresolved from './node_unresolved.json'
import python_multierror from './python_multierror.json'
import python_resolved from './python_resolved.json'

export const TEST_EVENTS = {
    javascript_empty,
    javascript_resolved,
    javascript_unresolved,
    node_unresolved,
    python_resolved,
    python_multierror,
}

export type TestEventName = keyof typeof TEST_EVENTS

export function getEventProperties(eventName: TestEventName): ErrorEventProperties {
    return TEST_EVENTS[eventName].properties
}

export function ExceptionLogicWrapper({
    eventName,
    loading = false,
    children,
}: {
    eventName: TestEventName
    loading?: boolean
    children: JSX.Element
}): JSX.Element {
    const properties = getEventProperties(eventName)
    const { setLoading } = useActions(exceptionCardLogic({ issueId: eventName }))
    useEffect(() => {
        setLoading(loading)
    }, [loading, setLoading])
    return (
        <BindLogic logic={errorPropertiesLogic} props={{ properties: properties, id: eventName }}>
            <BindLogic logic={exceptionCardLogic} props={{ issueId: eventName }}>
                {children}
            </BindLogic>
        </BindLogic>
    )
}
