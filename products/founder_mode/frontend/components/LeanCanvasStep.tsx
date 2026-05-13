import { useActions, useValues } from 'kea'

import { Button, cn, Label, Spinner, Textarea } from '@posthog/quill'

import { LEAN_CANVAS_CELLS, LeanCanvasCellConfig, LeanCanvasCellKey, leanCanvasLogic } from './leanCanvasLogic'

// Named grid areas mirror the canvas layout from the reference image:
//
//   +---------+----------+-----+----------+----------+
//   | problem | solution | usp | unfair   | customer |
//   |         +----------+     +----------+          |
//   |         | metrics  |     | channels |          |
//   +---------+----------+-----+----------+----------+
//   |    cost            |    revenue                |
//   +---------+----------+-----+----------+----------+
//
// problem / usp / customer span both top rows; cost spans 2 cols at the bottom and revenue
// spans the remaining 3. Keep the string format aligned column-by-column so a future reader
// can ASCII-eyeball the layout.
const GRID_AREAS = `"problem solution usp unfair customer"
"problem metrics usp channels customer"
"cost cost revenue revenue revenue"`

const CELL_AREA: Record<LeanCanvasCellKey, string> = {
    problem: 'problem',
    customer_segments: 'customer',
    usp: 'usp',
    solution: 'solution',
    unfair_advantage: 'unfair',
    revenue_stream: 'revenue',
    cost_structure: 'cost',
    key_metrics: 'metrics',
    channels: 'channels',
}

export function LeanCanvasStep(): JSX.Element {
    const { currentCell, filledCount, isFirstCell, isLastCell, savedProjectLoading } = useValues(leanCanvasLogic)
    const { nextCell, previousCell, completeAndContinue } = useActions(leanCanvasLogic)

    return (
        <div className="flex flex-col gap-6 w-full max-w-6xl">
            <header className="flex items-end justify-between gap-4">
                <div>
                    <h2 className="text-lg font-semibold text-text-primary">Lean canvas</h2>
                    <p className="text-sm text-text-secondary mt-1">
                        Fill in nine cells in the order shown. Each click on the canvas jumps to that cell, and your
                        progress saves whenever you move on.
                    </p>
                </div>
                <div className="text-xs text-text-secondary shrink-0">
                    {filledCount} of {LEAN_CANVAS_CELLS.length} filled
                </div>
            </header>

            <LeanCanvasViz />

            <ActiveCellPanel
                cell={currentCell}
                onNext={isLastCell ? completeAndContinue : nextCell}
                onPrevious={previousCell}
                isFirstCell={isFirstCell}
                isLastCell={isLastCell}
                saving={savedProjectLoading}
            />
        </div>
    )
}

function LeanCanvasViz(): JSX.Element {
    return (
        <div
            className="grid gap-2 w-full"
            style={{
                gridTemplateAreas: GRID_AREAS,
                gridTemplateColumns: 'repeat(5, minmax(0, 1fr))',
                // Top two rows for the 5-cell band, third row for cost / revenue. Auto sizing
                // keeps rows tall enough to display the cell value without truncation.
                gridTemplateRows: 'minmax(120px, auto) minmax(120px, auto) minmax(100px, auto)',
            }}
        >
            {LEAN_CANVAS_CELLS.map((cell) => (
                <CanvasCell key={cell.key} cell={cell} />
            ))}
        </div>
    )
}

function CanvasCell({ cell }: { cell: LeanCanvasCellConfig }): JSX.Element {
    const { ideation, filledByKey, currentCellIndex } = useValues(leanCanvasLogic)
    const { goToCell } = useActions(leanCanvasLogic)

    const isActive = LEAN_CANVAS_CELLS[currentCellIndex].key === cell.key
    const isFilled = filledByKey[cell.key]
    const value = ideation[cell.key]

    return (
        <button
            type="button"
            onClick={() => goToCell(cell.order - 1)}
            style={{ gridArea: CELL_AREA[cell.key] }}
            data-attr={`lean-canvas-cell-${cell.key}`}
            className={cn(
                'group relative rounded-md border-2 p-3 text-left transition-all overflow-hidden cursor-pointer flex flex-col gap-2',
                isActive && 'border-text-primary bg-surface-primary shadow-sm',
                !isActive && isFilled && 'border-border bg-fill-highlight-50 hover:bg-fill-highlight-100',
                !isActive && !isFilled && 'border-dashed border-border bg-surface-primary/40 hover:bg-surface-primary'
            )}
        >
            <div className="flex items-start justify-between gap-2">
                <div className="flex flex-col">
                    <span
                        className={cn(
                            'text-[10px] font-semibold uppercase tracking-wide',
                            isFilled ? 'text-text-primary' : 'text-text-secondary'
                        )}
                    >
                        {cell.title}
                    </span>
                </div>
                <span
                    className={cn(
                        'inline-flex items-center justify-center w-6 h-6 rounded-full text-[11px] font-semibold shrink-0',
                        isActive
                            ? 'bg-text-primary text-bg-primary'
                            : isFilled
                              ? 'bg-fill-highlight-200 text-text-primary'
                              : 'bg-fill-highlight-100 text-text-secondary'
                    )}
                >
                    {cell.order}
                </span>
            </div>
            <div className="flex-1 min-h-0 overflow-hidden">
                {value ? (
                    <p className="text-[11px] leading-snug text-text-primary whitespace-pre-wrap line-clamp-6">
                        {value}
                    </p>
                ) : (
                    <p className="text-[11px] italic text-text-tertiary leading-snug">
                        {isActive ? 'Type in the panel below — it fills here live.' : 'Click to fill'}
                    </p>
                )}
            </div>
        </button>
    )
}

interface ActiveCellPanelProps {
    cell: LeanCanvasCellConfig
    onNext: () => void
    onPrevious: () => void
    isFirstCell: boolean
    isLastCell: boolean
    saving: boolean
}

function ActiveCellPanel({
    cell,
    onNext,
    onPrevious,
    isFirstCell,
    isLastCell,
    saving,
}: ActiveCellPanelProps): JSX.Element {
    const { ideation } = useValues(leanCanvasLogic)
    const { setCellValue } = useActions(leanCanvasLogic)
    const value = ideation[cell.key]

    return (
        <div className="rounded-lg border border-border bg-surface-primary p-4 flex flex-col gap-3">
            <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                    <span className="inline-flex items-center justify-center w-7 h-7 rounded-full bg-text-primary text-bg-primary text-xs font-semibold">
                        {cell.order}
                    </span>
                    <div>
                        <span className="text-[10px] uppercase tracking-wide text-text-secondary">{cell.title}</span>
                        <h3 className="text-base font-medium text-text-primary">{cell.prompt}</h3>
                    </div>
                </div>
                {saving && (
                    <span className="inline-flex items-center gap-1 text-[11px] text-text-secondary">
                        <Spinner className="size-3" />
                        Saving…
                    </span>
                )}
            </div>
            <div>
                <Label htmlFor={`lean-canvas-cell-${cell.key}`} className="text-xs text-text-secondary">
                    Your answer
                </Label>
                <Textarea
                    id={`lean-canvas-cell-${cell.key}`}
                    value={value}
                    onChange={(e) => setCellValue(cell.key, e.target.value)}
                    placeholder={cell.placeholder}
                    rows={4}
                    className="mt-1 resize-none"
                    data-attr={`lean-canvas-input-${cell.key}`}
                />
            </div>
            <p className="text-xs text-text-secondary leading-relaxed">{cell.helper}</p>
            <div className="flex items-center justify-between gap-2 mt-1">
                <Button variant="outline" onClick={onPrevious} disabled={isFirstCell} data-attr="lean-canvas-back">
                    Back
                </Button>
                <Button
                    variant="primary"
                    onClick={onNext}
                    disabled={saving}
                    data-attr={isLastCell ? 'lean-canvas-finish' : 'lean-canvas-next'}
                >
                    {isLastCell ? 'Save & continue to validation' : 'Next'}
                </Button>
            </div>
        </div>
    )
}
