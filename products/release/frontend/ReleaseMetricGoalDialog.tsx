import { useState } from 'react'

import {
    Button,
    Dialog,
    DialogBody,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
    Field,
    FieldLabel,
    Input,
    Label,
    RadioGroup,
    RadioGroupItem,
} from '@posthog/quill'

import type { MetricGoalApi, ReleaseGoalDirectionEnumApi } from './generated/api.schemas'

export function ReleaseMetricGoalDialog({
    insightId,
    metricName,
    goal,
    onSave,
    onClose,
}: {
    insightId: number
    metricName: string
    goal: MetricGoalApi | undefined
    onSave: (goal: MetricGoalApi | null) => void
    onClose: () => void
}): JSX.Element {
    const [direction, setDirection] = useState<ReleaseGoalDirectionEnumApi>(goal?.direction ?? 'at_least')
    const [value, setValue] = useState(goal ? String(goal.value) : '')
    const target = value.trim() === '' ? NaN : Number(value)
    const valid = Number.isFinite(target)

    return (
        <Dialog open onOpenChange={(open: boolean) => !open && onClose()}>
            <DialogContent>
                <form
                    onSubmit={(event) => {
                        event.preventDefault()
                        if (valid) {
                            onSave({ insight_id: insightId, direction, value: target })
                        }
                    }}
                >
                    <DialogHeader>
                        <DialogTitle>{goal ? 'Edit goal' : 'Set a goal'}</DialogTitle>
                        <DialogDescription>
                            Pick the value {metricName} should reach. The metric shows whether it is on track.
                        </DialogDescription>
                    </DialogHeader>
                    <DialogBody>
                        <div className="flex flex-col gap-4">
                            <RadioGroup
                                value={direction}
                                onValueChange={(next) => setDirection(next as ReleaseGoalDirectionEnumApi)}
                                className="flex gap-4"
                            >
                                <div className="flex items-center gap-2">
                                    <RadioGroupItem value="at_least" id="release-goal-at-least" />
                                    <Label htmlFor="release-goal-at-least">At least</Label>
                                </div>
                                <div className="flex items-center gap-2">
                                    <RadioGroupItem value="at_most" id="release-goal-at-most" />
                                    <Label htmlFor="release-goal-at-most">At most</Label>
                                </div>
                            </RadioGroup>
                            <Field>
                                <FieldLabel htmlFor="release-goal-value">Target</FieldLabel>
                                <Input
                                    id="release-goal-value"
                                    type="number"
                                    inputMode="decimal"
                                    step="any"
                                    autoFocus
                                    value={value}
                                    onChange={(event) => setValue(event.target.value)}
                                    data-attr="release-metric-goal-value"
                                />
                            </Field>
                        </div>
                    </DialogBody>
                    <DialogFooter>
                        {goal && (
                            <Button
                                type="button"
                                variant="link-muted"
                                className="mr-auto"
                                onClick={() => onSave(null)}
                                data-attr="release-metric-goal-remove"
                            >
                                Remove goal
                            </Button>
                        )}
                        <Button type="button" variant="outline" onClick={onClose}>
                            Cancel
                        </Button>
                        <Button type="submit" variant="primary" disabled={!valid} data-attr="release-metric-goal-save">
                            Save goal
                        </Button>
                    </DialogFooter>
                </form>
            </DialogContent>
        </Dialog>
    )
}
