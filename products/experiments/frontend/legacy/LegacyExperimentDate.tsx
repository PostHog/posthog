import { TZLabel } from 'lib/components/TZLabel'
import { Label } from 'lib/ui/Label/Label'

/**
 * @deprecated Use the new ExperimentDate component instead
 */
export const LegacyExperimentDate = ({
    label,
    date,
    'data-attr': dataAttr,
}: {
    label: string
    date?: string | null
    'data-attr'?: string
}): JSX.Element | null => {
    if (!date) {
        return null
    }

    return (
        <div className="block" data-attr={dataAttr}>
            <Label intent="menu">{label}</Label>
            <div className="flex">
                <TZLabel time={date} />
            </div>
        </div>
    )
}
