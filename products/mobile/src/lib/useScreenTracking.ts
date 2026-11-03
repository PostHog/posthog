import { useGlobalSearchParams, useSegments } from 'expo-router'
import { useEffect, useLayoutEffect, useRef } from 'react'

import { type AnalyticsProperties, setAnalyticsScreenContext, trackScreen } from './analytics'
import { isReportId } from './ids'

function isGroup(segment: string): boolean {
    return segment.startsWith('(') && segment.endsWith(')')
}

/**
 * The route pattern without layout groups, such as `inbox`, `report/[id]` or `views/insight/[shortId]`. Dynamic
 * segments keep their bracket names, so one screen never splits into one name per id.
 */
export function screenName(segments: readonly string[]): string {
    const parts = segments.filter((segment) => !isGroup(segment))
    return parts.length > 0 ? parts.join('/') : 'index'
}

export function screenEntityProperties(name: string, params: Record<string, unknown>): AnalyticsProperties {
    const result: AnalyticsProperties = {}
    const id = typeof params.id === 'string' ? params.id : undefined
    if ((name === 'report/[id]' || name === 'report/[id]/details') && id && isReportId(id, true)) {
        result.report_id = id
    }
    if (name === 'views/dashboard/[id]' && id && /^(?:[1-9][0-9]*|demo-[a-z0-9-]+)$/.test(id)) {
        result.dashboard_id = id
    }
    if (name === 'views/insight/[shortId]' || name === 'views/chart/[shortId]') {
        if (typeof params.shortId === 'string' && /^[A-Za-z0-9_-]{1,64}$/.test(params.shortId)) {
            result.insight_short_id = params.shortId
        }
    }
    if (name === 'chat') {
        for (const [param, property] of [
            ['taskId', 'task_id'],
            ['runId', 'run_id'],
            ['reportId', 'report_id'],
        ] as const) {
            const value = params[param]
            if (typeof value === 'string' && isReportId(value, true)) {
                result[property] = value
            }
        }
    }
    return result
}

/** Sends one `$screen` per semantic destination, keeping route patterns as the screen names. */
export function useScreenTracking(enabled: boolean): void {
    const segments = useSegments()
    const params = useGlobalSearchParams()
    const name = screenName(segments)
    const properties = screenEntityProperties(name, params)
    const entityKey = JSON.stringify(properties)
    const latest = useRef({ key: entityKey, properties })
    if (latest.current.key !== entityKey) {
        latest.current = { key: entityKey, properties }
    }
    const entities = latest.current.properties
    const last = useRef<string | null>(null)

    useLayoutEffect(() => {
        setAnalyticsScreenContext(enabled ? { screen: name, ...entities } : {})
        return () => setAnalyticsScreenContext({})
    }, [enabled, name, entities])

    useEffect(() => {
        // `index` only redirects, so it is not a screen a person sees.
        if (!enabled || name === 'index') {
            return
        }
        const key = `${name}|${entityKey}`
        if (last.current === key) {
            return
        }
        last.current = key
        trackScreen(name, entities)
    }, [enabled, name, entityKey, entities])
}
