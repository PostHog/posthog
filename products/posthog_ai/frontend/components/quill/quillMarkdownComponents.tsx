import {
    Card,
    CardContent,
    Table,
    TableBody,
    TableCell,
    TableHead,
    TableHeader,
    TableRow,
    cn,
} from '@posthog/quill-primitives'

import type { LemonMarkdownComponents } from 'lib/lemon-ui/LemonMarkdown'

import { quillCardBorderClass } from './quillCardBorder'

type CellAlign = 'left' | 'center' | 'right'

// GFM writes a column's alignment onto each cell; quill takes it as a prop instead of an inline style.
function cellAlign(node: unknown): CellAlign | undefined {
    const align = (node as { properties?: { align?: unknown } } | undefined)?.properties?.align
    return align === 'left' || align === 'center' || align === 'right' ? align : undefined
}

export const QUILL_MARKDOWN_COMPONENTS: LemonMarkdownComponents = {
    table: ({ node: _node, children }) => (
        // No header, so no header gap on top.
        <Card size="sm" flush className={cn('pt-0', quillCardBorderClass())}>
            <CardContent>
                <Table size="sm">{children}</Table>
            </CardContent>
        </Card>
    ),
    thead: ({ node: _node, children }) => <TableHeader>{children}</TableHeader>,
    tbody: ({ node: _node, children }) => <TableBody>{children}</TableBody>,
    tr: ({ node: _node, children }) => <TableRow>{children}</TableRow>,
    th: ({ node, children }) => <TableHead align={cellAlign(node)}>{children}</TableHead>,
    td: ({ node, children }) => <TableCell align={cellAlign(node)}>{children}</TableCell>,
}
