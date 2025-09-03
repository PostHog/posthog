import { Children, useState } from 'react'

import { IconCopy, IconExternal } from '@posthog/icons'
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
            <span
                className="inline-flex align-middle"
                onMouseEnter={() => setOpen(true)}
                onMouseLeave={() => setOpen(false)}
            >
                <PropertyWrapper title={short} visible>
                    <CommitIcon className="text-sm text-secondary" />
                </PropertyWrapper>
            </span>
        </Popover>
    )
}

export function MultipleReleasesPreview({ count, overlay }: { count: number; overlay: JSX.Element }): JSX.Element {
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
            <span
                className="inline-flex align-middle"
                onMouseEnter={() => setOpen(true)}
                onMouseLeave={() => setOpen(false)}
            >
                <PropertyWrapper title={`${count} related releases`} visible>
                    <CommitIcon className="text-sm text-secondary" />
                </PropertyWrapper>
            </span>
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
                            <div className="w-28 text-xs text-muted">Commit SHA</div>
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

export function CommitIcon({ className }: { className?: string }): JSX.Element {
    return (
        <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 512 512"
            className={className}
            fill="currentColor"
            aria-hidden="true"
        >
            <path d="M448,224H380a128,128,0,0,0-247.9,0H64a32,32,0,0,0,0,64h68.05A128,128,0,0,0,380,288H448a32,32,0,0,0,0-64ZM256,320a64,64,0,1,1,64-64A64.07,64.07,0,0,1,256,320Z" />
        </svg>
    )
}
