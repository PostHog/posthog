import { useValues } from 'kea'
import { useCallback } from 'react'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { FingerprintRecordPartDisplay } from 'lib/components/Errors/FingerprintRecordPartDisplay'
import { ChainedStackTraces, ExceptionHeaderProps } from 'lib/components/Errors/StackTraces'
import { errorPropertiesLogic } from 'lib/components/Errors/errorPropertiesLogic'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { cn } from 'lib/utils/css-classes'

import { cancelEvent } from '../../../utils'
import { RuntimeIcon } from '../../RuntimeIcon'
import { exceptionCardLogic } from '../exceptionCardLogic'
import { StacktraceBaseDisplayProps, StacktraceBaseExceptionHeaderProps } from './StacktraceBase'

export function StacktraceGenericDisplay({
    className,
    truncateMessage,
    renderLoading,
    renderEmpty,
}: StacktraceBaseDisplayProps): JSX.Element {
    const { exceptionAttributes, hasStacktrace } = useValues(errorPropertiesLogic)
    const { loading, showAllFrames } = useValues(exceptionCardLogic)
    const { runtime } = exceptionAttributes || {}
    const renderExceptionHeader = useCallback(
        ({ type, value, loading, part }: ExceptionHeaderProps): JSX.Element => {
            return (
                <StacktraceGenericExceptionHeader
                    type={type}
                    value={value}
                    part={part}
                    runtime={runtime}
                    loading={loading}
                    truncate={truncateMessage}
                />
            )
        },
        [runtime, truncateMessage]
    )
    return (
        <div className={className}>
            {loading ? (
                renderLoading(renderExceptionHeader)
            ) : (
                <ChainedStackTraces
                    showAllFrames={showAllFrames}
                    renderExceptionHeader={renderExceptionHeader}
                    onFrameContextClick={(_, e) => cancelEvent(e)}
                />
            )}
            {!loading && !hasStacktrace && renderEmpty()}
        </div>
    )
}

export function StacktraceGenericExceptionHeader({
    type,
    value,
    runtime,
    part,
    loading,
    truncate,
}: StacktraceBaseExceptionHeaderProps): JSX.Element {
    const isScriptError = value === 'Script error' && runtime === 'web' && type === 'Error'

    return (
        <div className="pb-1">
            <div className="flex h-6 items-center gap-2">
                {loading ? (
                    <LemonSkeleton className="h-2 w-[25%]" />
                ) : (
                    <>
                        {runtime && <RuntimeIcon runtime={runtime} />}
                        <div className="text-lg font-bold">{type || 'Unknown type'}</div>
                        {part && <FingerprintRecordPartDisplay part={part} />}
                    </>
                )}
            </div>
            <div
                className={cn('text-tertiary leading-6', {
                    'line-clamp-1': truncate,
                })}
            >
                {loading ? (
                    <LemonSkeleton className="h-2 w-[50%]" />
                ) : isScriptError ? (
                    <Tooltip
                        title="This error occurs when JavaScript errors are caught by the browser but details are hidden due to cross-origin restrictions."
                        docLink="https://posthog.com/docs/error-tracking/common-questions#what-is-a-script-error-with-no-stack-traces"
                        placement="right-end"
                        delayMs={50}
                    >
                        <span>{value}</span>
                    </Tooltip>
                ) : (
                    value || 'Unknown message'
                )}
            </div>
        </div>
    )
}
