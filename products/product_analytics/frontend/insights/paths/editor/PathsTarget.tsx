import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import { EditorFilterProps } from '~/types'

import { LemonPathsTarget } from './LemonPathsTarget'
import { QuillPathsTarget } from './QuillPathsTarget'

export type PathTargetProps = {
    position: 'start' | 'end'
} & EditorFilterProps

export function PathsTargetStart(props: EditorFilterProps): JSX.Element {
    return <PathsTarget position="start" {...props} />
}

export function PathsTargetEnd(props: EditorFilterProps): JSX.Element {
    return <PathsTarget position="end" {...props} />
}

function PathsTarget(props: PathTargetProps): JSX.Element {
    const quillEnabled = useFeatureFlag('TODAY_RAIL_NAV')
    return quillEnabled ? <QuillPathsTarget {...props} /> : <LemonPathsTarget {...props} />
}
