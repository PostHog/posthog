import type { ChartSetting, ChartSettingValue } from './buildChartSettings'
import { ChartSettingChoice } from './ChartSettingChoice'
import { ChartSettingNumber } from './ChartSettingNumber'
import { ChartSettingSelect } from './ChartSettingSelect'
import { ChartSettingSwitch } from './ChartSettingSwitch'
import { ChartSettingText } from './ChartSettingText'

export function ChartSettingRow({
    setting,
    onChange,
}: {
    setting: ChartSetting
    onChange: (value: ChartSettingValue) => void
}): JSX.Element {
    switch (setting.kind) {
        case 'switch':
            return <ChartSettingSwitch setting={setting} onChange={onChange} />
        case 'choice':
            return <ChartSettingChoice setting={setting} onChange={onChange} />
        case 'select':
            return <ChartSettingSelect setting={setting} onChange={onChange} />
        case 'text':
            return <ChartSettingText setting={setting} onChange={onChange} />
        case 'number':
            return <ChartSettingNumber setting={setting} onChange={onChange} />
    }
}
