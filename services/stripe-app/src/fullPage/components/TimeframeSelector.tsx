import { Button, Menu, MenuItem } from '@stripe/ui-extension-sdk/ui'

import { getTimeframe, TIMEFRAMES } from '../../constants'

interface Props {
    value: string
    onChange: (value: string) => void
}

const TimeframeSelector = ({ value, onChange }: Props): JSX.Element => (
    <Menu
        onAction={(key) => onChange(String(key))}
        trigger={
            <Button size="small" type="secondary">
                Date range: {getTimeframe(value).label}
            </Button>
        }
    >
        {TIMEFRAMES.map((t) => (
            <MenuItem key={t.value} id={t.value}>
                {t.label}
            </MenuItem>
        ))}
    </Menu>
)

export default TimeframeSelector
