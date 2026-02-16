import { useState } from 'react'

import { IconChevronRight } from '@posthog/icons'

function segmentsToPath(segments: string[]): string {
    return segments
        .map((segment, index) => {
            if (/^\d+$/.test(segment)) {
                return `[${segment}]`
            }
            return index > 0 ? `.${segment}` : segment
        })
        .join('')
}

function ValuePreview({ value }: { value: unknown }): JSX.Element {
    if (value === null) {
        return <span className="text-muted">null</span>
    }
    if (value === undefined) {
        return <span className="text-muted">undefined</span>
    }
    if (typeof value === 'string') {
        return <span className="text-warning">"{value.length > 80 ? value.slice(0, 80) + '…' : value}"</span>
    }
    if (typeof value === 'number') {
        return <span className="text-success">{value}</span>
    }
    if (typeof value === 'boolean') {
        return <span className="text-link">{String(value)}</span>
    }
    if (Array.isArray(value)) {
        return <span className="text-muted">[{value.length} items]</span>
    }
    if (typeof value === 'object') {
        return <span className="text-muted">{'{…}'}</span>
    }
    return <span className="text-muted">{String(value)}</span>
}

function TreeNode({
    name,
    value,
    segments,
    depth,
    onPathSelect,
    selectedPath,
}: {
    name: string | null
    value: unknown
    segments: string[]
    depth: number
    onPathSelect: (path: string) => void
    selectedPath: string | null
}): JSX.Element {
    const [expanded, setExpanded] = useState(depth < 1)
    const isExpandable = value !== null && typeof value === 'object'
    const path = segmentsToPath(segments)
    const isSelected = selectedPath === path

    const entries = isExpandable
        ? Array.isArray(value)
            ? value.map((v, i) => [String(i), v] as const)
            : Object.entries(value as Record<string, unknown>)
        : []

    return (
        <div className={depth > 0 ? 'ml-4' : ''}>
            <div className="flex items-center gap-1 group">
                {isExpandable ? (
                    <button
                        className="flex items-center p-0 border-0 bg-transparent cursor-pointer text-muted"
                        onClick={() => setExpanded(!expanded)}
                    >
                        <IconChevronRight className={`w-3 h-3 transition-transform ${expanded ? 'rotate-90' : ''}`} />
                    </button>
                ) : (
                    <span className="w-3" />
                )}
                {name !== null && (
                    <>
                        <button
                            className={`p-0 px-0.5 border-0 rounded cursor-pointer font-mono text-xs leading-relaxed ${
                                isSelected
                                    ? 'bg-primary-highlight text-primary-dark font-bold'
                                    : 'bg-transparent hover:bg-primary-highlight text-default'
                            }`}
                            onClick={() => onPathSelect(path)}
                            title={`Use path: ${path}`}
                        >
                            {name}
                        </button>
                        <span className="text-muted">:</span>
                    </>
                )}
                {!isExpandable ? (
                    <ValuePreview value={value} />
                ) : !expanded ? (
                    <button className="p-0 border-0 bg-transparent cursor-pointer" onClick={() => setExpanded(true)}>
                        <ValuePreview value={value} />
                    </button>
                ) : null}
            </div>

            {isExpandable && expanded && (
                <div>
                    {entries.map(([key, val]) => (
                        <TreeNode
                            key={key}
                            name={key}
                            value={val}
                            segments={[...segments, key]}
                            depth={depth + 1}
                            onPathSelect={onPathSelect}
                            selectedPath={selectedPath}
                        />
                    ))}
                </div>
            )}
        </div>
    )
}

interface OutputTestResultTreeProps {
    data: unknown
    onPathSelect: (path: string) => void
    selectedPath?: string | null
}

export function OutputTestResultTree({ data, onPathSelect, selectedPath }: OutputTestResultTreeProps): JSX.Element {
    if (data !== null && typeof data === 'object') {
        const entries = Array.isArray(data)
            ? data.map((v, i) => [String(i), v] as const)
            : Object.entries(data as Record<string, unknown>)

        return (
            <div className="font-mono text-xs">
                {entries.map(([key, val]) => (
                    <TreeNode
                        key={key}
                        name={key}
                        value={val}
                        segments={[key]}
                        depth={0}
                        onPathSelect={onPathSelect}
                        selectedPath={selectedPath ?? null}
                    />
                ))}
            </div>
        )
    }

    return (
        <div className="font-mono text-xs p-1">
            <ValuePreview value={data} />
        </div>
    )
}
