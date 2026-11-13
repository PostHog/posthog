import { useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { Item, ItemActions, ItemContent, ItemTitle, Text, cn } from '@posthog/quill'

import { dayjs } from 'lib/dayjs'
import { SignalNode } from 'scenes/debug/signals/types'

import { getSourceProductMeta } from '../../badges/sourceProductIcons'
import { ReportStageProse } from './ReportStageProse'

/**
 * The first sentence of a signal, so a row states one finding and the rest waits behind the click.
 * A first line that only introduces what follows ("New issue created:") gives way to the next line.
 */
function signalHeadline(content: string): string {
    const lines = content
        .trim()
        .split('\n')
        .map((line) => line.trim())
        .filter(Boolean)
    // The row is plain text, so inline code marks would show as literal backticks.
    const line = (lines[0]?.endsWith(':') && lines[1] ? lines[1] : (lines[0] ?? '')).replace(/`/g, '')
    const sentenceEnd = line.search(/[.!?](\s|$)/)
    return sentenceEnd === -1 ? line : line.slice(0, sentenceEnd + 1)
}

export function ReportEvidenceRow({ signal }: { signal: SignalNode }): JSX.Element {
    const [expanded, setExpanded] = useState(false)
    const source = getSourceProductMeta(signal.source_product)
    const time = dayjs(signal.timestamp)
    const detailId = `inbox-report-evidence-${signal.signal_id}`

    return (
        <div className={cn('rounded-md transition-colors duration-150', expanded && 'bg-muted')}>
            <Item
                variant="default"
                size="sm"
                render={<button type="button" aria-expanded={expanded} aria-controls={detailId} />}
                onClick={() => setExpanded(!expanded)}
                className={cn(
                    'group/row w-full rounded-md border-0 px-2 py-2 text-left',
                    expanded && 'hover:bg-transparent'
                )}
                data-attr="inbox-report-evidence-row"
            >
                <ItemContent className="min-w-0">
                    <ItemTitle className="max-w-full min-w-0 font-normal text-foreground">
                        <span className={cn('min-w-0 break-words', !expanded && 'line-clamp-2')}>
                            {signalHeadline(signal.content)}
                        </span>
                    </ItemTitle>
                </ItemContent>
                <ItemActions className="shrink-0 self-start pt-0.5">
                    <Text
                        size="xs"
                        variant="muted"
                        render={<span />}
                        className="flex items-center gap-1.5 whitespace-nowrap"
                    >
                        {source && <source.Icon aria-hidden className="size-3.5" />}
                        {source && <span className="hidden @md:inline">{source.label}</span>}
                        <time dateTime={signal.timestamp} title={time.format('LLL')} className="w-12 text-right">
                            {time.format('MMM D')}
                        </time>
                        <IconChevronDown
                            aria-hidden
                            className={cn('size-3.5 transition-transform duration-200', expanded && 'rotate-180')}
                        />
                    </Text>
                </ItemActions>
            </Item>
            {expanded && (
                <div id={detailId} className="px-2 pb-3">
                    <ReportStageProse markdown={signal.content} tone="muted" size="xs" />
                </div>
            )}
        </div>
    )
}
