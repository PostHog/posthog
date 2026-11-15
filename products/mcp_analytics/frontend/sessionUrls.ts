import { combineUrl } from 'kea-router'

import { urls } from 'scenes/urls'

import { AnyPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

function sessionsUrl(searchParams: Record<string, any>, sessionId?: string): string {
    const { search: _search, properties, ...rest } = searchParams
    const otherProperties = Array.isArray(properties)
        ? properties.filter((filter) => filter?.key !== '$session_id' || filter?.type !== PropertyFilterType.Event)
        : []
    const nextProperties = sessionId
        ? [
              ...otherProperties,
              {
                  key: '$session_id',
                  value: [sessionId],
                  operator: PropertyOperator.Exact,
                  type: PropertyFilterType.Event,
              } satisfies AnyPropertyFilter,
          ]
        : otherProperties

    return combineUrl(urls.mcpAnalyticsSessions(), {
        ...rest,
        ...(nextProperties.length > 0 ? { properties: nextProperties } : {}),
    }).url
}

export function mcpSessionUrl(sessionId: string, searchParams: Record<string, any> = {}): string {
    return sessionsUrl(searchParams, sessionId)
}

export function mcpSessionsUrl(searchParams: Record<string, any> = {}): string {
    return sessionsUrl(searchParams)
}
