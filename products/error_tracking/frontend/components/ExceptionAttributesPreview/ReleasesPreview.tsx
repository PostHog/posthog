import { Children, useState } from 'react'

import { IconCode, IconCopy, IconExternal } from '@posthog/icons'
import { LemonButton, LemonTag } from '@posthog/lemon-ui'

import { ExceptionRelease } from 'lib/components/Errors/types'
import { Link } from 'lib/lemon-ui/Link'
import { Popover } from 'lib/lemon-ui/Popover/Popover'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

export function ReleasesPreview({ releases }: { releases?: ExceptionRelease[] }): JSX.Element {
    if (!releases || releases.length === 0) {
        return <></>
    }

    const overlay = <ReleasesPopoverContent releases={releases} />

    if (releases.length === 1) {
        return <SingleReleasePreview release={releases[0]} overlay={overlay} />
    }

    return <MultipleReleasesPreview count={releases.length} overlay={overlay} />
}

export function SingleReleasePreview({
    release,
    overlay,
}: {
    release: ExceptionRelease
    overlay: JSX.Element
}): JSX.Element {
    const short = release.commitSha.slice(0, 7)
    const [open, setOpen] = useState(false)
    return (
        <Popover
            visible={open}
            overlay={overlay}
            placement="right"
            showArrow
            onMouseEnterInside={() => setOpen(true)}
            onMouseLeaveInside={() => setOpen(false)}
        >
            <PropertyWrapper
                title={short}
                visible
                onMouseEnter={() => setOpen(true)}
                onMouseLeave={() => setOpen(false)}
            >
                <IconCode className="text-sm text-secondary" />
            </PropertyWrapper>
        </Popover>
    )
}

export function MultipleReleasesPreview({ count, overlay }: { count: number; overlay: JSX.Element }): JSX.Element {
    const [open, setOpen] = useState(false)
    return (
        <Popover
            visible={open}
            overlay={overlay}
            placement="top"
            showArrow
            onMouseEnterInside={() => setOpen(true)}
            onMouseLeaveInside={() => setOpen(false)}
        >
            <PropertyWrapper
                title={`${count} related releases`}
                visible
                onMouseEnter={() => setOpen(true)}
                onMouseLeave={() => setOpen(false)}
            >
                <IconCode className="text-sm text-secondary" />
            </PropertyWrapper>
        </Popover>
    )
}

export function ReleasesPopoverContent({ releases }: { releases: ExceptionRelease[] }): JSX.Element {
    return (
        <div className="min-w-[24rem] max-w-[40rem]">
            <div className="flex justify-between items-center border-b-1 p-1">
                <h4 className="mb-0 px-1">Related releases</h4>
            </div>
            <div className="p-2 space-y-3">
                {releases.map((r, idx) => (
                    <div key={r.commitSha} className="space-y-2">
                        <div className="flex items-center gap-2">
                            <div className="w-28 text-xs text-muted flex items-center gap-1">
                                <IconCode className="text-muted" />
                                <span>Commit SHA</span>
                            </div>
                            <div className="flex-1 flex items-center gap-2 min-w-0">
                                <div className="font-mono text-xs break-all" title={r.commitSha}>
                                    {r.commitSha.slice(0, 7)}...
                                </div>
                                <LemonButton
                                    size="xsmall"
                                    icon={<IconCopy />}
                                    tooltip="Copy commit SHA"
                                    onClick={() => copyToClipboard(r.commitSha)}
                                />
                            </div>
                        </div>
                        {r.url && (
                            <div className="flex items-center gap-2">
                                <div className="w-28 text-xs text-muted">URL</div>
                                <div className="flex-1 min-w-0">
                                    <Link
                                        to={r.url}
                                        target="_blank"
                                        className="text-xs break-all inline-flex items-center gap-1"
                                    >
                                        <span className="truncate" title={r.url}>
                                            {r.url}
                                        </span>
                                        <IconExternal className="size-3" />
                                    </Link>
                                </div>
                            </div>
                        )}
                        {idx < releases.length - 1 && <div className="-mx-2 border-t-1" />}
                    </div>
                ))}
            </div>
        </div>
    )
}

function PropertyWrapper({
    title,
    visible = true,
    children,
    onMouseEnter,
    onMouseLeave,
}: {
    title?: string
    visible?: boolean
    children: JSX.Element
    onMouseEnter?: () => void
    onMouseLeave?: () => void
}): JSX.Element {
    if (Children.count(children) == 0 || title === undefined || !visible) {
        return <></>
    }
    return (
        <LemonTag className="bg-fill-primary" onMouseEnter={onMouseEnter} onMouseLeave={onMouseLeave}>
            {children}
            <span className="capitalize">{title}</span>
        </LemonTag>
    )
}
