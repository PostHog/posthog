import { ChevronLeft } from 'lucide-react'
import { type ReactElement, type ReactNode, useCallback, useState } from 'react'

// TODO(quill): delete this file once @posthog/quill ships a list↔detail
// navigation primitive (working titles: `MasterDetail`, `ListDetail`, or a
// stack-based `Navigator`). Migration is then a render-prop swap.
//
// What's needed from Quill:
//   - Managed view-state for `list | loading | detail`, with async loading
//     while the caller fetches the detail row. Today we own this in a
//     three-variant `useState<ViewState>` and run the caller's `onItemClick`
//     promise inline.
//   - A back-affordance that integrates with the host's navigation. We use
//     `<Button variant="link-muted" size="sm">` + a lucide `<ChevronLeft>`
//     because that's the closest visual to a "go back" link in Quill today.
//     A real Quill primitive could expose this as a slot and hook into a
//     `Navigator` history stack.
//   - A loading-while-fetching slot. We route through Quill's `Empty` +
//     `Spinner` (semantically a transient placeholder, same shape as an
//     empty state) — a primitive could absorb this with a `loadingMessage`
//     prop and avoid every caller spelling out the `EmptyHeader` /
//     `EmptyMedia` composition.
//   - Generic over both list-row and detail shapes (`<TItem, TDetail>`)
//     since some callers fetch a richer detail object than the list row.
//
// Until then this file leans on Quill's `Button`, `Spinner`, `Empty*` and
// design tokens so the visual language already matches what a future Quill
// primitive would ship.
import { Button, Empty, EmptyDescription, EmptyHeader, EmptyMedia, Spinner } from '@posthog/quill'

export interface ListDetailViewProps<TItem, TDetail = TItem> {
    onItemClick: ((item: TItem) => Promise<TDetail | null>) | undefined
    backLabel: string
    getItemName: (item: TItem) => string
    renderDetail: (detail: TDetail) => ReactNode
    renderList: (handleClick: (item: TItem) => void) => ReactNode
}

type ViewState<TDetail> = { view: 'list' } | { view: 'loading'; name: string } | { view: 'detail'; detail: TDetail }

function BackLink({ label, onClick }: { label: string; onClick: () => void }): ReactElement {
    return (
        <Button variant="link-muted" size="sm" onClick={onClick} className="self-start gap-1 px-0">
            <ChevronLeft className="h-3.5 w-3.5" />
            {label}
        </Button>
    )
}

export function ListDetailView<TItem, TDetail = TItem>({
    onItemClick,
    backLabel,
    getItemName,
    renderDetail,
    renderList,
}: ListDetailViewProps<TItem, TDetail>): ReactElement {
    const [viewState, setViewState] = useState<ViewState<TDetail>>({ view: 'list' })

    const handleClick = useCallback(
        async (item: TItem) => {
            if (!onItemClick) {
                return
            }

            setViewState({ view: 'loading', name: getItemName(item) })
            const detail = await onItemClick(item).catch((error) => {
                console.error(`Error loading detail:`, error)
                return null
            })

            if (detail) {
                setViewState({ view: 'detail', detail })
            } else {
                setViewState({ view: 'list' })
            }
        },
        [onItemClick, getItemName]
    )

    const handleBack = useCallback(() => setViewState({ view: 'list' }), [])

    if (viewState.view === 'loading') {
        return (
            <div className="p-4">
                <div className="flex flex-col gap-2">
                    <BackLink label={backLabel} onClick={handleBack} />
                    <Empty className="py-10">
                        <EmptyHeader>
                            <EmptyMedia variant="icon">
                                <Spinner />
                            </EmptyMedia>
                            <EmptyDescription>Loading {viewState.name}…</EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                </div>
            </div>
        )
    }

    if (viewState.view === 'detail') {
        return (
            <div className="p-4">
                <div className="flex flex-col gap-2">
                    <BackLink label={backLabel} onClick={handleBack} />
                    {renderDetail(viewState.detail)}
                </div>
            </div>
        )
    }

    return <>{renderList(handleClick)}</>
}
