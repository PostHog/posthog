import { useDebouncedValue } from 'lib/hooks/useDebouncedValue'
import { LemonTableLoader } from 'lib/lemon-ui/LemonTable/LemonTableLoader'

import { LOADING_FEEDBACK_DELAY_MS } from './loadingFeedback'

/** The LemonTable refresh bar, for quill tables. Render it inside a `relative` wrapper around the table. */
export function TableLoadingBar({ loading }: { loading: boolean }): JSX.Element | null {
    const show = useDebouncedValue(loading, LOADING_FEEDBACK_DELAY_MS, false)
    return <LemonTableLoader loading={show} placement="top" />
}
