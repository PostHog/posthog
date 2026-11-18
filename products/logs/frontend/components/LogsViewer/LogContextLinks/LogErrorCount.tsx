import { useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'

import {
    TraceErrorsLogicProps,
    traceErrorsLogic,
} from 'products/tracing/frontend/components/TraceDrawer/traceErrorsLogic'
import type { ErrorScope } from 'products/tracing/frontend/errorCorrelation'

import type { LogContextLinksSurface } from './LogContextLinks'

const SCOPE_WHERE: Record<ErrorScope, string> = {
    span: 'in this span',
    trace: 'in this trace',
    session: 'in this session',
}

export interface LogErrorCountProps {
    logicProps: TraceErrorsLogicProps
    surface: LogContextLinksSurface
    onOpenRelatedErrors: (scope: ErrorScope) => void
}

export function LogErrorCount({ logicProps, surface, onOpenRelatedErrors }: LogErrorCountProps): JSX.Element | null {
    const { issues, issuesLoading, issuesFailed, effectiveScope } = useValues(traceErrorsLogic(logicProps))

    if (!effectiveScope) {
        return null
    }

    const where = SCOPE_WHERE[effectiveScope]
    const errorCount = issues.reduce((sum, issue) => sum + issue.occurrences, 0)

    if (!issuesLoading && !issuesFailed && errorCount === 0) {
        return (
            <span className="text-xs text-secondary" data-attr={`logs-${surface}-context-no-errors`}>
                {`No errors ${where}`}
            </span>
        )
    }

    return (
        <LemonButton
            size="xsmall"
            type="secondary"
            status={issuesLoading || issuesFailed ? 'default' : 'danger'}
            icon={<IconWarning />}
            loading={issuesLoading}
            onClick={() => onOpenRelatedErrors(effectiveScope)}
            data-attr={`logs-${surface}-context-errors`}
        >
            {issuesLoading
                ? `Counting errors ${where}`
                : issuesFailed
                  ? "Couldn't count errors"
                  : `${pluralize(errorCount, 'error')} ${where}`}
        </LemonButton>
    )
}
