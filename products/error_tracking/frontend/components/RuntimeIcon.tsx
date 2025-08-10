import { ErrorTrackingRuntime } from 'lib/components/Errors/types'
import { IconJavascript, IconNodeJS, IconPython, LemonIconProps } from 'lib/lemon-ui/icons'
import React from 'react'

const RuntimeIconMap = {
    python: IconPython,
    web: IconJavascript,
    node: IconNodeJS,
    unknown: React.Fragment,
}

export function RuntimeIcon({ runtime, ...props }: { runtime: ErrorTrackingRuntime } & LemonIconProps): JSX.Element {
    const Icon = RuntimeIconMap[runtime]
    return <Icon {...props} />
}
