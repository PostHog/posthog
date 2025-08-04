import { ErrorTrackingRuntime } from 'lib/components/Errors/types'
import {
    IconCSharp,
    IconGolang,
    IconJavascript,
    IconNodeJS,
    IconPHP,
    IconPython,
    IconRuby,
    IconRust,
    LemonIconProps,
} from 'lib/lemon-ui/icons'
import { IconLogomark } from '@posthog/icons'

const RuntimeIconMap = {
    python: IconPython,
    web: IconJavascript,
    node: IconNodeJS,
    ruby: IconRuby,
    go: IconGolang,
    rust: IconRust,
    dotnet: IconCSharp,
    php: IconPHP,

    unknown: IconLogomark,
}

export function RuntimeIcon({ runtime, ...props }: { runtime: ErrorTrackingRuntime } & LemonIconProps): JSX.Element {
    const Icon = RuntimeIconMap[runtime]
    return <Icon {...props} />
}
