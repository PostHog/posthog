import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonFunnelStepOrderPicker } from './LemonFunnelStepOrderPicker'
import { QuillFunnelStepOrderPicker } from './QuillFunnelStepOrderPicker'

export function FunnelStepOrderPicker(): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillFunnelStepOrderPicker /> : <LemonFunnelStepOrderPicker />
}
