import { ErrorTrackingRuntime } from 'lib/components/Errors/types'
import {
    IconPython,
    IconJavascript,
    IconNode,
    IconRuby,
    IconGo,
    IconRust,
    IconCSharp,
    IconLogomark,
    IconPHP,
    IconJava,
    IconAndroid,
    IconApple,
    IconReact,
    IconElixir,
    IconSwift,
    IconDart,
    IconFlutter,
} from '@posthog/icons'
import { IconProps } from '@posthog/icons/dist/src/types/icon-types'

const RuntimeIconMap: Record<ErrorTrackingRuntime, React.FC> = {
    python: IconPython,
    web: IconJavascript,
    node: IconNode,
    ruby: IconRuby,
    go: IconGo,
    rust: IconRust,
    dotnet: IconCSharp,
    php: IconPHP,
    java: IconJava,
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
