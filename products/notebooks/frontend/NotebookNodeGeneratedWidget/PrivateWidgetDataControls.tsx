import posthog from 'posthog-js'
import { useEffect, useRef, useState } from 'react'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { readableErrorMessage } from 'lib/api-error'

import type { WidgetFrameApi } from '../generated/api.schemas'
import type { WidgetFrameSession } from './widgetFrameSession'

interface PrivateWidgetFrames {
    run: (names: string[]) => Promise<void>
    page: (name: string, offset: number, limit: number) => WidgetFrameApi | undefined
    loading: boolean
    error?: string
    generation: number
    status?: string
}

export function usePrivateWidgetFrames(
    versionId: string | null,
    inputs: WidgetFrameSession['privateInputs']
): PrivateWidgetFrames {
    const [result, setResult] = useState<{
        versionId: string
        inputKey: string
        generation: number
        frames: Map<string, WidgetFrameApi>
    }>()
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string>()
    const controller = useRef<AbortController | null>(null)
    useEffect(() => {
        setLoading(false)
        setError(undefined)
        setResult(undefined)
        return () => controller.current?.abort()
    }, [versionId])
    const current = inputs && versionId === result?.versionId ? result : undefined

    async function run(names: string[]): Promise<void> {
        if (!inputs || !versionId) {
            return
        }
        controller.current?.abort()
        const request = new AbortController()
        controller.current = request
        setLoading(true)
        setError(undefined)
        try {
            const frames = new Map<string, WidgetFrameApi>()
            for (const name of names) {
                frames.set(name, await inputs.compute(name, request.signal))
            }
            if (!request.signal.aborted) {
                setResult((previous) => ({
                    versionId,
                    inputKey: inputs.key,
                    generation: (previous?.generation ?? 0) + 1,
                    frames,
                }))
                posthog.capture('notebook app widget data ran', { input_count: frames.size })
            }
        } catch (failure) {
            if (!request.signal.aborted) {
                setError(
                    readableErrorMessage(failure) || 'Could not run the widget data. Check your access and try again.'
                )
            }
        } finally {
            if (!request.signal.aborted) {
                setLoading(false)
            }
        }
    }

    function page(name: string, offset: number, limit: number): WidgetFrameApi | undefined {
        const frame = current?.frames.get(name)
        if (!frame) {
            return
        }
        const rows = frame.rows.slice(offset, offset + limit)
        const end = offset + rows.length
        const more = end < frame.totalRowCount
        return { ...frame, rows, offset, includedRowCount: rows.length, nextOffset: more ? end : null, truncated: more }
    }

    return {
        run,
        page,
        loading,
        error,
        generation: current?.generation ?? 0,
        status: current
            ? inputs?.key === current.inputKey
                ? 'Showing your calculation.'
                : 'Inputs changed. Run again to update the widget.'
            : undefined,
    }
}

export function PrivateWidgetDataControls({
    enabled,
    names,
    data,
    onRun,
}: {
    enabled: boolean
    names: string[]
    data: PrivateWidgetFrames
    onRun: () => void
}): JSX.Element | null {
    if (!enabled || !names.length) {
        return null
    }
    return (
        <>
            <div className="flex flex-wrap items-center gap-2 border-b p-2">
                <LemonButton size="small" type="secondary" loading={data.loading} onClick={onRun}>
                    Run widget data for me
                </LemonButton>
                {data.status && (
                    <span role="status" className="text-secondary">
                        {data.status}
                    </span>
                )}
            </div>
            {data.error && (
                <LemonBanner type="error" className="m-2">
                    {data.error}
                </LemonBanner>
            )}
        </>
    )
}
