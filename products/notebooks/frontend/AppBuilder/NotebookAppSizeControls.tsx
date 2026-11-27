import { useId, useState } from 'react'

import { LemonInput } from '@posthog/lemon-ui'

import { LemonLabel } from 'lib/lemon-ui/LemonLabel'
import { clamp } from 'lib/utils/numbers'

import type { NotebookAppBlockApi } from '../generated/api.schemas'
import { MAX_CARD_HEIGHT, MIN_CARD_HEIGHT } from './NotebookAppCard'

type CardSize = Pick<NotebookAppBlockApi, 'width' | 'height'>

export function NotebookAppSizeControls({
    width = 12,
    height,
    onChange,
}: CardSize & { onChange: (size: CardSize) => void }): JSX.Element {
    const widthId = useId()
    const heightId = useId()
    const [heightDraft, setHeightDraft] = useState<number>()
    return (
        <>
            <div className="flex items-center justify-between">
                <LemonLabel htmlFor={widthId}>Width</LemonLabel>
                <span className="text-xs text-secondary">{width} / 12 columns</span>
            </div>
            <input
                id={widthId}
                type="range"
                min={1}
                max={12}
                value={width}
                aria-valuetext={`${width} of 12 columns`}
                data-attr="notebook-app-component-width"
                onChange={(event) => onChange({ width: event.target.valueAsNumber })}
            />
            <LemonLabel htmlFor={heightId}>Height</LemonLabel>
            <LemonInput
                id={heightId}
                type="number"
                min={MIN_CARD_HEIGHT}
                max={MAX_CARD_HEIGHT}
                value={heightDraft ?? height ?? NaN}
                placeholder="Auto"
                suffix={<span className="text-secondary">px</span>}
                data-attr="notebook-app-component-height"
                onChange={(value) => {
                    const draft = value ?? NaN
                    setHeightDraft(draft)
                    const nextHeight = Number.isFinite(draft)
                        ? clamp(Math.round(draft), MIN_CARD_HEIGHT, MAX_CARD_HEIGHT)
                        : undefined
                    if (nextHeight !== height) {
                        onChange({ height: nextHeight })
                    }
                }}
                onBlur={() => setHeightDraft(undefined)}
                onPressEnter={(event) => event.currentTarget.blur()}
            />
        </>
    )
}
