import { useActions, useValues } from 'kea'

import { LemonButton, Spinner } from '@posthog/lemon-ui'

import { CONTEXT_KIND_NAME } from '../../lib/ciExplorerContext'
import { providerName } from '../../lib/ciExplorerDetails'
import { ciExplorerContextLogic } from '../../scenes/ciExplorerContextLogic'
import { CIExplorerContextComparison } from './CIExplorerContextComparison'
import { CIExplorerProviderMark } from './CIExplorerProviderMark'

/** The selected workflow, matrix, job, or step against its recent runs on the default branch. */
export function CIExplorerContext(): JSX.Element {
    const { selection, context, answerLoading, failed } = useValues(ciExplorerContextLogic)
    const { retry } = useActions(ciExplorerContextLogic)

    if (!selection) {
        return <p className="m-0 text-xs text-secondary">Select a workflow or a job to compare it.</p>
    }
    return (
        <>
            <div>
                <h3 className="m-0 break-words text-sm font-semibold">{selection.label}</h3>
                <p className="m-0 mt-1 flex items-center gap-1.5 text-xs text-secondary">
                    {CONTEXT_KIND_NAME[selection.kind]}
                    <span aria-hidden="true">·</span>
                    <CIExplorerProviderMark engine={selection.engine} />
                    {providerName(selection.engine)}
                </p>
            </div>
            {context ? (
                <CIExplorerContextComparison selection={selection} context={context} />
            ) : failed && !answerLoading ? (
                <div className="flex flex-col items-start gap-2">
                    <p className="m-0 text-xs text-secondary">Couldn't load timings.</p>
                    <LemonButton type="secondary" size="small" onClick={retry} data-attr="ci-explorer-context-retry">
                        Retry
                    </LemonButton>
                </div>
            ) : (
                <p className="m-0 flex items-center gap-2 text-xs text-secondary" role="status">
                    <Spinner /> Loading timings
                </p>
            )}
        </>
    )
}
