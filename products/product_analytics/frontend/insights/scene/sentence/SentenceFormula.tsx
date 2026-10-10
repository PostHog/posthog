import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { IconX } from '@posthog/icons'
import { Button, Input, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { EditableWord } from './EditableWord'
import { insightSentenceLogic } from './insightSentenceLogic'

/** The formula that combines the events. The word also shows while a first formula is written, and then opens by itself. */
export function SentenceFormula({
    insightProps,
    label,
}: {
    insightProps: InsightLogicProps
    label: string
}): JSX.Element {
    const { formulas, formulaPending } = useValues(insightSentenceLogic(insightProps))
    const { setFormulas, setFormulaPending } = useActions(insightSentenceLogic(insightProps))
    const [open, setOpen] = useState(formulaPending)
    const [drafts, setDrafts] = useState<string[]>(formulas.length ? formulas : [''])

    useEffect(() => {
        if (formulaPending) {
            setOpen(true)
        }
    }, [formulaPending])

    const apply = (): void => {
        setFormulas(drafts)
        setOpen(false)
    }

    return (
        <Popover
            open={open}
            onOpenChange={(nextOpen) => {
                setOpen(nextOpen)
                if (nextOpen) {
                    setDrafts(formulas.length ? formulas : [''])
                } else if (formulaPending) {
                    setFormulaPending(false)
                }
            }}
        >
            <PopoverTrigger render={<EditableWord color="purple" data-attr="quill-insight-sentence-formula" />}>
                {label}
            </PopoverTrigger>
            <PopoverContent align="start" aria-label="Formula" className="w-80 gap-3">
                <Text size="xs" variant="muted">
                    Use the letter beside each event, for example A / B or A + B.
                </Text>
                <div className="flex flex-col gap-2">
                    {drafts.map((draft, index) => (
                        <div key={index} className="flex items-center gap-2">
                            <Input
                                value={draft}
                                placeholder="A / B"
                                aria-label={drafts.length > 1 ? `Formula ${index + 1}` : 'Formula'}
                                onChange={(event: React.ChangeEvent<HTMLInputElement>) =>
                                    setDrafts(drafts.map((value, i) => (i === index ? event.target.value : value)))
                                }
                                onKeyDown={(event: React.KeyboardEvent<HTMLInputElement>) => {
                                    if (event.key === 'Enter') {
                                        apply()
                                    }
                                }}
                                data-attr="quill-insight-formula-input"
                            />
                            {drafts.length > 1 && (
                                <Button
                                    size="icon-sm"
                                    aria-label={`Remove formula ${index + 1}`}
                                    onClick={() => setDrafts(drafts.filter((_, i) => i !== index))}
                                    data-attr="quill-insight-formula-remove-one"
                                >
                                    <IconX />
                                </Button>
                            )}
                        </div>
                    ))}
                </div>
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <Button
                        variant="link"
                        size="sm"
                        onClick={() => setDrafts([...drafts, ''])}
                        data-attr="quill-insight-formula-add"
                    >
                        Add another formula
                    </Button>
                    <div className="flex items-center gap-2">
                        {formulas.length > 0 && (
                            <Button
                                variant="outline"
                                size="sm"
                                onClick={() => {
                                    setFormulas([])
                                    setOpen(false)
                                }}
                                data-attr="quill-insight-formula-remove"
                            >
                                Remove formula
                            </Button>
                        )}
                        <Button variant="primary" size="sm" onClick={apply} data-attr="quill-insight-formula-apply">
                            Apply
                        </Button>
                    </div>
                </div>
            </PopoverContent>
        </Popover>
    )
}
