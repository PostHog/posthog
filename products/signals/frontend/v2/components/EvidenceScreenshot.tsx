import { IconCursorClick, IconWarning } from '@posthog/icons'

import { DemoScreenshot, DemoScreenshotKind } from '../types'

function GhostTile(): JSX.Element {
    return (
        <div className="flex h-14 flex-col justify-between rounded-sm border border-primary p-1.5">
            <div className="h-1.5 w-10 rounded-sm bg-fill-tertiary" />
            <div className="flex items-end gap-0.5">
                {[5, 9, 7, 12, 10, 14, 11].map((height, index) => (
                    // Bar heights sketch a fake sparkline; each needs its own pixel value
                    // oxlint-disable-next-line react/forbid-dom-props
                    <div key={index} className="w-1.5 rounded-sm bg-fill-tertiary" style={{ height }} />
                ))}
            </div>
        </div>
    )
}

function DashboardTileMock(): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            <div className="h-2 w-24 rounded-sm bg-fill-tertiary" />
            <div className="grid grid-cols-2 gap-1.5">
                <GhostTile />
                <div className="flex h-14 flex-col items-start justify-center gap-1 rounded-sm border border-danger bg-danger-highlight p-1.5">
                    <span className="flex items-center gap-1 text-[8px] leading-tight font-semibold text-danger">
                        <IconWarning className="text-[10px]" />
                        There was a problem completing this query
                    </span>
                    <span className="rounded-sm border border-primary bg-surface-primary px-1 py-0.5 text-[8px] leading-none">
                        Try again
                    </span>
                </div>
                <GhostTile />
                <GhostTile />
            </div>
        </div>
    )
}

function UsageBannerMock(): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            <div className="flex flex-col gap-1 rounded-sm border border-warning bg-warning-highlight p-1.5">
                <span className="flex items-center gap-1 text-[8px] leading-tight font-semibold">
                    <IconWarning className="text-[10px] text-warning" />
                    You have reached your usage limit. New events are not being saved.
                </span>
                <span className="flex items-center gap-1 text-[8px] leading-tight">
                    Upgrade your plan or raise your billing limit to keep your data.
                    <IconCursorClick className="text-[10px] text-secondary" />
                </span>
            </div>
            <div className="h-1.5 w-32 rounded-sm bg-fill-tertiary" />
            <div className="h-1.5 w-40 rounded-sm bg-fill-tertiary" />
            <div className="h-1.5 w-28 rounded-sm bg-fill-tertiary" />
        </div>
    )
}

function AiErrorCardMock(): JSX.Element {
    return (
        <div className="flex flex-col gap-1.5">
            <div className="ml-auto h-2 w-32 rounded-sm bg-fill-tertiary" />
            <div className="flex flex-col gap-1">
                <div className="h-1.5 w-36 rounded-sm bg-fill-tertiary" />
                <div className="flex h-14 items-center justify-center rounded-sm border border-danger bg-danger-highlight">
                    <span className="flex items-center gap-1 text-[8px] font-semibold text-danger">
                        <IconWarning className="text-[10px]" />
                        Something went wrong running this query
                    </span>
                </div>
            </div>
        </div>
    )
}

const MOCK_BY_KIND: Record<DemoScreenshotKind, () => JSX.Element> = {
    'dashboard-tile': DashboardTileMock,
    'usage-banner': UsageBannerMock,
    'ai-error-card': AiErrorCardMock,
}

/** Framed mock screenshot of the error UI: a browser chrome bar, a micro-mock, and its source. */
export function EvidenceScreenshot({ screenshot }: { screenshot: DemoScreenshot }): JSX.Element {
    const Mock = MOCK_BY_KIND[screenshot.kind]
    return (
        <figure className="m-0 flex flex-col gap-1.5" data-attr="v2-report-screenshot">
            <div className="overflow-hidden rounded border border-primary">
                <div className="flex items-center gap-1 border-b border-primary bg-surface-secondary px-2 py-1.5">
                    <span className="size-1.5 rounded-full bg-fill-tertiary" />
                    <span className="size-1.5 rounded-full bg-fill-tertiary" />
                    <span className="size-1.5 rounded-full bg-fill-tertiary" />
                    <span className="ml-1 flex-1 truncate rounded-sm bg-surface-primary px-1.5 py-0.5 font-mono text-[9px] text-tertiary">
                        {screenshot.urlHint}
                    </span>
                </div>
                <div className="bg-surface-primary p-2.5">
                    <Mock />
                </div>
            </div>
            <figcaption className="font-mono text-[11px] text-secondary">screenshot · {screenshot.source}</figcaption>
        </figure>
    )
}
