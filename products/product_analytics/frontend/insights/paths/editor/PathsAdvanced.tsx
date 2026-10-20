import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonPathsAdvanced } from './LemonPathsAdvanced'
import { QuillPathsAdvanced } from './QuillPathsAdvanced'

export function PathsAdvanced(props: EditorFilterProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillPathsAdvanced {...props} /> : <LemonPathsAdvanced {...props} />
}
