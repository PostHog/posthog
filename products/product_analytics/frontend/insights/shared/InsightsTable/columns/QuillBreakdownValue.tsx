import { ReactNode } from 'react'

import { IconExternal } from '@posthog/icons'
import { Badge, Button } from '@posthog/quill'

import { parseAliasToReadable } from 'lib/components/PathCleanFilters/PathCleanFilterItem'
import { LinkPrimitive } from 'lib/lemon-ui/Link'
import stringWithWBR from 'lib/utils/stringWithWBR'
import { isURL } from 'lib/utils/url'

import { BreakdownFilter } from '~/queries/schema/schema-general'

interface QuillBreakdownValueProps {
    label: string
    breakdownFilter?: BreakdownFilter | null
    /** "Current" or "Previous", shown when the breakdown value stands in for the series name. */
    compareValue?: string
    /** Shown right after the value, when the value stands in for the series name. */
    swatch?: ReactNode
}

export function QuillBreakdownValue({
    label,
    breakdownFilter,
    compareValue,
    swatch,
}: QuillBreakdownValueProps): JSX.Element {
    // Not for links: a link stays on one line, and Chrome still breaks a no-wrap line at a <wbr>.
    const formattedLabel = breakdownFilter?.breakdown_path_cleaning
        ? parseAliasToReadable(label)
        : stringWithWBR(label, 20)

    // Clipped with CSS only, so the full value stays in the DOM and copying the cell copies all of it. The table sizes
    // each column to its content, so the max width is what makes a long value wrap instead of widening the column.
    return (
        <span className="flex max-w-80 items-center gap-2">
            {label &&
                (isURL(label) ? (
                    <Button
                        variant="link-foreground"
                        size="sm"
                        nativeButton={false}
                        render={<LinkPrimitive to={label} target="_blank" />}
                        title={label}
                        // Lines the link text up with plain values, the column header and the swatch after it. Buttons block text
                        // selection, which would leave the URL out when someone copies rows.
                        className="-mx-2 min-w-0 max-w-full select-text"
                    >
                        <span className="truncate">{label}</span>
                        <IconExternal />
                    </Button>
                ) : (
                    <span title={label} className="line-clamp-4 font-medium">
                        {formattedLabel}
                    </span>
                ))}
            {swatch}
            {compareValue && <Badge>{compareValue}</Badge>}
        </span>
    )
}
