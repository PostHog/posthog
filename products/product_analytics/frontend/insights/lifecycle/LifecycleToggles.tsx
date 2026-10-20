import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonLifecycleToggles } from './LemonLifecycleToggles'
import { QuillLifecycleToggles } from './QuillLifecycleToggles'

export function LifecycleToggles(props: EditorFilterProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillLifecycleToggles {...props} /> : <LemonLifecycleToggles {...props} />
}
