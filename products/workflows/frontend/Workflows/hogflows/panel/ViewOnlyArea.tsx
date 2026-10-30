import { useValues } from 'kea'

import { workflowLogic } from '../../workflowLogic'

// A disabled <fieldset> would also disable collapse headers, and viewers need those to read nested settings.
export function ViewOnlyArea({ children }: { children: React.ReactNode }): JSX.Element {
    const { isViewOnly } = useValues(workflowLogic)

    return (
        <div
            data-view-only={isViewOnly || undefined}
            className="contents [&[data-view-only]_:is(input,textarea,select,button,.monaco-editor):not(.LemonCollapsePanel\_\_header)]:pointer-events-none [&[data-view-only]_:is(input,textarea,select,button,.monaco-editor):not(.LemonCollapsePanel\_\_header)]:opacity-60"
        >
            {children}
        </div>
    )
}
