import {
    IconAndroid,
    IconApple,
    IconCSharp,
    IconDart,
    IconElixir,
    IconFlutter,
    IconGo,
    IconJava,
    IconJavascript,
    IconKotlin,
    IconLogomark,
    IconNode,
    IconPHP,
    IconPython,
    IconReact,
    IconRuby,
    IconRust,
    IconSwift,
    type IconProps,
} from '@posthog/icons'

import { ErrorTrackingRuntime } from 'lib/components/Errors/types'

const RuntimeIconMap: Record<ErrorTrackingRuntime, React.FC<IconProps>> = {
    python: IconPython,
    web: IconJavascript,
    node: IconNode,
    convex: (props): JSX.Element => (
        <svg width="1em" height="1em" viewBox="0 0 24 24" {...props}>
            <image href="/static/services/convex.png" width="24" height="24" />
        </svg>
    ),
    ruby: IconRuby,
    go: IconGo,
    rust: IconRust,
    dotnet: IconCSharp,
    php: IconPHP,
    java: IconJava,
    kotlin: IconKotlin,
    android: IconAndroid,
    ios: IconApple,
    elixir: IconElixir,
    swift: IconSwift,
    dart: IconDart,
    flutter: IconFlutter,
    ['react-native']: IconReact,

    unknown: IconLogomark,
}

export function RuntimeIcon({ runtime, ...props }: { runtime: ErrorTrackingRuntime } & IconProps): JSX.Element {
    const Icon = RuntimeIconMap[runtime]
    return <Icon {...props} />
}
