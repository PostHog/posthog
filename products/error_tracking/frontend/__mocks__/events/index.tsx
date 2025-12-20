import { BindLogic, useActions } from 'kea'
import { useEffect } from 'react'

import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { ErrorEventProperties } from 'lib/components/Errors/types'

import { exceptionCardLogic } from '../../components/ExceptionCard/exceptionCardLogic'
import java_long from './java_long.json'
import javascript_empty from './javascript_empty.json'
import javascript_minified_react_error from './javascript_minified_react_error.json'
import javascript_no_in_app from './javascript_no_in_app.json'
import javascript_non_error_promise_rejection from './javascript_non_error_promise_rejection.json'
import javascript_resolved from './javascript_resolved.json'
import javascript_script_error from './javascript_script_error.json'
import javascript_unresolved from './javascript_unresolved.json'
import node_long_frame from './node_long_frame.json'
import node_unresolved from './node_unresolved.json'
import python_multierror from './python_multierror.json'
import python_resolved from './python_resolved.json'

export const TEST_EVENTS = {
    javascript_empty,
    javascript_resolved,
    javascript_unresolved,
    javascript_script_error,
    javascript_minified_react_error,
    javascript_non_error_promise_rejection,
    javascript_no_in_app,
    node_unresolved,
    python_resolved,
    python_multierror,
    node_long_frame,
    java_long,
}

export type TestEventName = keyof typeof TEST_EVENTS

export function getEventProperties(eventName: TestEventName): ErrorEventProperties {
    return TEST_EVENTS[eventName].properties
}

export function ExceptionLogicWrapper({
    eventName,
    loading = false,
    showAllFrames = false,
    children,
}: {
    eventName: TestEventName
    loading?: boolean
    showAllFrames?: boolean
    children: JSX.Element
}): JSX.Element {
    const exceptionCardProps = { issueId: eventName }

    const properties = getEventProperties(eventName)
    const { setLoading, setShowAllFrames } = useActions(exceptionCardLogic(exceptionCardProps))

    useEffect(() => {
        setLoading(loading)
    }, [loading, setLoading])

    useEffect(() => {
        if (showAllFrames) {
            setShowAllFrames(showAllFrames)
            // Fetch and set all frames
        }
    }, [showAllFrames, setShowAllFrames])

    return (
        <BindLogic logic={exceptionCardLogic} props={exceptionCardProps}>
            <BindLogic logic={errorPropertiesLogic} props={{ properties: properties, id: eventName }}>
                {children}
            </BindLogic>
        </BindLogic>
    )
}
