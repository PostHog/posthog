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
            <div className="flex gap-2 items-center h-6">
                {loading ? (
                    <LemonSkeleton className="w-[25%] h-2" />
                ) : (
                    <>
                        {runtime && <RuntimeIcon runtime={runtime} fontSize="0.9rem" className="ml-1" />}
                        <div className="font-semibold text-[1rem]">{type || 'Unknown type'}</div>
                        {part && <FingerprintRecordPartDisplay part={part} />}
                    </>
                )}
            </div>
            <div
                className={cn('font-medium text-[var(--gray-8)] leading-6', {
                    'line-clamp-1': truncate,
                })}
            >
                {loading ? (
                    <LemonSkeleton className="w-[50%] h-2" />
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
