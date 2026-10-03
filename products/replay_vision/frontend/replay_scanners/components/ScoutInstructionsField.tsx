import './ScoutInstructionsField.scss'

import { useEffect, useLayoutEffect, useRef } from 'react'

import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea/LemonTextArea'

import { SCOUT_PLACEHOLDER_PATTERN } from '../scannerScout'

/** Splits instructions into plain runs and the `<ALL CAPS>` slots an author still has to fill. */
function segments(value: string): { text: string; placeholder: boolean }[] {
    const parts: { text: string; placeholder: boolean }[] = []
    let index = 0
    // A fresh regex per call: the shared one carries /g, and a lastIndex left over from a previous
    // caller would silently skip the first match here.
    const pattern = new RegExp(SCOUT_PLACEHOLDER_PATTERN.source, 'g')
    let match = pattern.exec(value)
    while (match) {
        if (match.index > index) {
            parts.push({ text: value.slice(index, match.index), placeholder: false })
        }
        parts.push({ text: match[0], placeholder: true })
        index = match.index + match[0].length
        match = pattern.exec(value)
    }
    if (index < value.length) {
        parts.push({ text: value.slice(index), placeholder: false })
    }
    return parts
}

/** The scout instructions editor, with unfilled `<ALL CAPS>` placeholders painted bold and red.
 *
 * A textarea can't style its own contents, so what you read is a backdrop div rendering the same
 * string; the textarea sits on top contributing the caret and selection over transparent glyphs.
 * `ScoutInstructionsField.scss` holds every metric the two layers share, and explains why. */
export function ScoutInstructionsField({
    value,
    onChange,
    minRows,
    maxRows,
    dataAttr,
}: {
    value: string
    onChange: (value: string) => void
    minRows?: number
    maxRows?: number
    dataAttr?: string
}): JSX.Element {
    const backdropRef = useRef<HTMLDivElement | null>(null)
    const textAreaRef = useRef<HTMLTextAreaElement | null>(null)

    // The field autosizes, so its scroll offset only moves once the content passes `maxRows`.
    const syncScroll = (): void => {
        if (backdropRef.current && textAreaRef.current) {
            backdropRef.current.scrollTop = textAreaRef.current.scrollTop
            backdropRef.current.scrollLeft = textAreaRef.current.scrollLeft
        }
    }
    useLayoutEffect(syncScroll, [value])
    // `LemonTextArea` forwards only a few textarea attributes, and `onScroll` isn't among them, so
    // the listener goes on the element itself rather than widening the shared component.
    useEffect(() => {
        const element = textAreaRef.current
        element?.addEventListener('scroll', syncScroll)
        return () => element?.removeEventListener('scroll', syncScroll)
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [])

    return (
        <div className="ScoutInstructionsField">
            <div ref={backdropRef} aria-hidden className="ScoutInstructionsField__backdrop">
                {segments(value).map((segment, index) =>
                    segment.placeholder ? (
                        <strong key={index} className="ScoutInstructionsField__placeholder">
                            {segment.text}
                        </strong>
                    ) : (
                        <span key={index}>{segment.text}</span>
                    )
                )}
                {/* A trailing newline is collapsed when it ends the div's content, which would drop
                    the backdrop a line behind the textarea while typing at the end. */}
                {'\n'}
            </div>
            <LemonTextArea
                ref={textAreaRef}
                value={value}
                onChange={onChange}
                minRows={minRows}
                maxRows={maxRows}
                className="ScoutInstructionsField__field"
                data-attr={dataAttr}
            />
        </div>
    )
}
