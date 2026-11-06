import { useActions, useValues } from 'kea'
import { useEffect, useState } from 'react'

import { LemonInput, Tooltip } from '@posthog/lemon-ui'

import { metricsViewerLogic, sanitizeFormulaInput } from './metricsViewerLogic'

// Committed on blur/Enter (mirroring TrendsFormula) so a half-typed formula doesn't fire
// a query per keystroke. Input is lowercased — clause aliases are lowercase and the
// backend parser is case-sensitive.
export function MetricsFormulaInput({ disabledReason }: { disabledReason: string | null }): JSX.Element {
    const { formula } = useValues(metricsViewerLogic)
    const { setFormula } = useActions(metricsViewerLogic)
    const [draft, setDraft] = useState(formula)

    // An external change (URL restore, clause reset) replaces the local draft.
    useEffect(() => {
        setDraft(formula)
    }, [formula])

    const commit = (): void => {
        if (draft !== formula) {
            setFormula(draft)
        }
    }

    return (
        <Tooltip title="Arithmetic over the series letters, with + - * / and parentheses. Only the formula result is charted.">
            <LemonInput
                size="small"
                className="min-w-48"
                value={draft}
                onChange={(value) => setDraft(sanitizeFormulaInput(value))}
                onBlur={commit}
                onPressEnter={commit}
                placeholder="Formula, e.g. (a - b) / a"
                data-attr="metrics-viewer-formula"
                disabledReason={disabledReason}
            />
        </Tooltip>
    )
}
