import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { LemonFunnelStepReferencePicker } from './LemonFunnelStepReferencePicker'
import { QuillFunnelStepReferencePicker } from './QuillFunnelStepReferencePicker'

export function FunnelStepReferencePicker(): JSX.Element | null {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillFunnelStepReferencePicker /> : <LemonFunnelStepReferencePicker />
}
