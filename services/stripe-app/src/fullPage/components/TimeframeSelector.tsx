import { Chip, Menu, MenuItem } from '@stripe/ui-extension-sdk/ui'

import { getTimeframe, TIMEFRAMES } from '../../constants'

interface Props {
    value: string
    onChange: (value: string) => void
}

const TimeframeSelector = ({ value, onChange }: Props): JSX.Element => (
    <Menu
        onAction={(key) => onChange(String(key))}
        trigger={<Chip label="Date range" value={getTimeframe(value).label} />}
    >
        {TIMEFRAMES.map((t) => (
            <MenuItem key={t.value} id={t.value}>
                {t.label}
            </MenuItem>
        ))}
    </Menu>
)

export default TimeframeSelector
