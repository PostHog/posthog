import { LemonCollapse } from '@posthog/lemon-ui'

import { HeatmapPageFields, HeatmapPageFieldsProps } from './HeatmapPageFields'

export interface HeatmapAdvancedSettingsProps extends HeatmapPageFieldsProps {
    header?: string
}

export function HeatmapAdvancedSettings({
    header = 'Advanced settings',
    ...props
}: HeatmapAdvancedSettingsProps): JSX.Element {
    return <LemonCollapse panels={[{ key: 'advanced', header, content: <HeatmapPageFields {...props} /> }]} />
}
