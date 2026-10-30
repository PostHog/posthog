import { useValues } from 'kea'

import { workflowLogic } from '../../workflowLogic'

export function ViewOnlyFieldset({ children }: { children: React.ReactNode }): JSX.Element {
    const { isViewOnly } = useValues(workflowLogic)

    return (
        <fieldset
            disabled={isViewOnly}
            className="contents [&:disabled_:is(button,input,textarea)]:cursor-not-allowed [&:disabled_:is(button,input,textarea)]:opacity-60"
        >
            {children}
        </fieldset>
    )
}
