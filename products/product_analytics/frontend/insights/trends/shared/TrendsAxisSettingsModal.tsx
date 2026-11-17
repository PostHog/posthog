import { useActions, useValues } from 'kea'

import { LemonButton, LemonCheckbox, LemonModal, LemonSegmentedButton } from '@posthog/lemon-ui'

import { InsightLogicProps } from '~/types'

import { trendsAxisSettingsLogic } from './trendsAxisSettingsLogic'

export function TrendsAxisSettingsModal({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { axis, entries } = useValues(trendsAxisSettingsLogic(insightProps))
    const { selectAxis, setSeriesPosition, closeModal, save, resetAxes } = useActions(
        trendsAxisSettingsLogic(insightProps)
    )
    if (!axis) {
        return null
    }
    return (
        <LemonModal
            isOpen
            title={axis === 'left' ? 'Left Y-axis settings' : 'Right Y-axis settings'}
            onClose={closeModal}
            width={520}
            footer={
                <div className="flex w-full flex-wrap justify-between gap-2">
                    <LemonButton onClick={resetAxes} data-attr="trends-axes-reset">
                        Use automatic axes
                    </LemonButton>
                    <div className="flex gap-2">
                        <LemonButton type="secondary" onClick={closeModal}>
                            Cancel
                        </LemonButton>
                        <LemonButton type="primary" onClick={save} data-attr="trends-axis-save">
                            Save axis
                        </LemonButton>
                    </div>
                </div>
            }
        >
            <LemonSegmentedButton
                value={axis}
                onChange={selectAxis}
                options={[
                    { value: 'left', label: 'Left Y-axis' },
                    { value: 'right', label: 'Right Y-axis' },
                ]}
            />
            <h3 className="mt-4">Series on this axis</h3>
            <p className="text-secondary">
                {`Selected series share this scale. Other series use the ${axis === 'left' ? 'right' : 'left'} Y-axis.`}
            </p>
            <div className="flex flex-col gap-3">
                {entries.map((entry) => (
                    <LemonCheckbox
                        key={entry.key}
                        checked={entry.position === axis}
                        label={entry.label}
                        onChange={(checked) =>
                            setSeriesPosition(entry.key, checked ? axis : axis === 'left' ? 'right' : 'left')
                        }
                    />
                ))}
            </div>
        </LemonModal>
    )
}
