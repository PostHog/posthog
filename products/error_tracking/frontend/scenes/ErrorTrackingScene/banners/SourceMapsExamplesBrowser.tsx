import { Card, CardGroup, Text } from 'lib/ui/quill'
import { cn } from 'lib/utils/css-classes'
import { pluralize } from 'lib/utils/strings'

import type { MissingSymbolsExampleApi, MissingSymbolsExamplesApi } from '../../../generated/api.schemas'
import { SourceMapsExampleDetail } from './SourceMapsExampleDetail'
import { SOURCE_MAPS_PLATFORM_LABELS } from './sourceMapsFixWizardLogic'

function exampleSummary(example: MissingSymbolsExampleApi, exceptionsLoaded: boolean): string {
    const frames = pluralize(example.frames, 'frame')
    if (!exceptionsLoaded) {
        return frames
    }
    const issues =
        example.issue_count_capped && example.issue_count > 0
            ? `${example.issue_count}+ issues`
            : pluralize(example.issue_count, 'issue')
    return `${frames} · ${issues}`
}

export function SourceMapsExamplesBrowser({
    examples,
    selectedIndex,
    onSelect,
    onRetry,
    onOpenException,
}: {
    examples: MissingSymbolsExamplesApi
    selectedIndex: number
    onSelect: (index: number) => void
    onRetry: () => void
    onOpenException: () => void
}): JSX.Element {
    const selected = examples.results[selectedIndex] ?? examples.results[0]

    return (
        <div className="@container" data-quill>
            <div className="grid grid-cols-1 gap-4 @3xl:grid-cols-5">
                <CardGroup className="self-start @3xl:col-span-2">
                    {examples.results.map((example, index) => (
                        <Card key={index} size="sm" className="p-0">
                            <button
                                type="button"
                                onClick={() => onSelect(index)}
                                aria-pressed={example === selected}
                                data-attr="error-tracking-source-maps-examples-item"
                                className={cn(
                                    'flex w-full flex-col gap-0.5 px-3 py-2 text-left hover:bg-fill-hover focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring',
                                    example === selected && 'bg-fill-selected'
                                )}
                            >
                                <span className="truncate font-mono text-xs" translate="no">
                                    {example.location ?? 'Unknown file'}
                                </span>
                                <Text size="xs" variant="muted">
                                    {exampleSummary(example, examples.exceptions_loaded)}
                                </Text>
                            </button>
                        </Card>
                    ))}
                </CardGroup>
                {selected ? (
                    <div className="@3xl:col-span-3">
                        <SourceMapsExampleDetail
                            example={selected}
                            missingLabel={SOURCE_MAPS_PLATFORM_LABELS[examples.platform].symbol}
                            exceptionsLoaded={examples.exceptions_loaded}
                            lookbackHours={examples.lookback_hours}
                            onRetry={onRetry}
                            onOpenException={onOpenException}
                        />
                    </div>
                ) : null}
            </div>
        </div>
    )
}
