import { Text } from '@posthog/quill'

export function ReportStageSectionTitle({ children }: { children: string }): JSX.Element {
    return (
        <Text size="base" weight="semibold" render={<h2 className="m-0" />}>
            {children}
        </Text>
    )
}
