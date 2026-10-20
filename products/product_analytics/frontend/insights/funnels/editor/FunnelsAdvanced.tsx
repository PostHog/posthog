import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonFunnelsAdvanced } from './LemonFunnelsAdvanced'
import { QuillFunnelsAdvanced } from './QuillFunnelsAdvanced'

export function FunnelsAdvanced(props: EditorFilterProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillFunnelsAdvanced {...props} /> : <LemonFunnelsAdvanced {...props} />
}
