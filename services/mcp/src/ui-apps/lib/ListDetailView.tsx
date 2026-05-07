import { ChevronLeft } from 'lucide-react'
import { type ReactElement, type ReactNode, useCallback, useState } from 'react'

import { Button, Spinner } from '@posthog/quill'

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
                    <div className="flex items-center justify-center gap-2 py-10 text-sm text-muted-foreground">
                        <Spinner className="h-4 w-4" />
                        <span>Loading {viewState.name}…</span>
                    </div>
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
