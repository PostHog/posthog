import { ChevronLeft } from 'lucide-react'
import { type ReactElement, type ReactNode, useCallback, useState } from 'react'

import { Button, Empty, EmptyDescription, EmptyHeader, EmptyMedia, Spinner } from '@posthog/quill'

export interface ListDetailViewProps<TItem, TDetail = TItem> {
    onItemClick: ((item: TItem) => Promise<TDetail | null>) | undefined
    backLabel: string
    getItemName: (item: TItem) => string
    renderDetail: (detail: TDetail) => ReactNode
    renderList: (handleClick: (item: TItem) => void) => ReactNode
}

type ViewState<TDetail> =
    | { view: 'list' }
    | { view: 'loading'; name: string }
    | { view: 'detail'; detail: TDetail }
    | { view: 'error'; name: string; message: string }

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

            const name = getItemName(item)
            setViewState({ view: 'loading', name })
            try {
                const detail = await onItemClick(item)
                if (detail) {
                    setViewState({ view: 'detail', detail })
                } else {
                    // `Promise<TDetail | null>` is part of the contract — a null resolution
                    // is the caller saying "no detail to show", not a failure.
                    setViewState({ view: 'error', name, message: `No details available for ${name}.` })
                }
            } catch (error) {
                console.error(`Error loading detail:`, error)
                setViewState({ view: 'error', name, message: `Couldn't load ${name}.` })
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

    if (viewState.view === 'error') {
        return (
            <div className="p-4">
                <div className="flex flex-col gap-2">
                    <BackLink label={backLabel} onClick={handleBack} />
                    <Empty className="py-10">
                        <EmptyHeader>
                            <EmptyDescription>{viewState.message}</EmptyDescription>
                        </EmptyHeader>
                    </Empty>
                </div>
            </div>
        )
    }

    return <>{renderList(handleClick)}</>
}
