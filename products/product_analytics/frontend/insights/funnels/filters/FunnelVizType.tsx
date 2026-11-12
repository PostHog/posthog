import { LemonSelect } from 'lib/lemon-ui/LemonSelect'

import { EditorFilterProps, FunnelVizType as VizType } from '~/types'

import { useFunnelVizType } from './useFunnelVizType'

type LabelProps = {
    icon: JSX.Element
    title: string
}
const Label = ({ icon, title }: LabelProps): JSX.Element => (
    <div className="flex items-center text-sm font-medium gap-1">
        {icon} {title}
    </div>
)

type LabelInMenuProps = {
    icon: JSX.Element
    title: string
    description: string
}
const LabelInMenu = ({ icon, title, description }: LabelInMenuProps): JSX.Element => (
    <div>
        <div className="flex items-center text-sm font-medium gap-1">
            {icon} {title}
        </div>
        <div className="text-secondary text-xs mt-1">{description}</div>
    </div>
)

export function FunnelVizType({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): JSX.Element | null {
    const { value, options, setValue } = useFunnelVizType({ insightProps })

    if (value === VizType.Flow) {
        return null
    }

    return (
        <LemonSelect
            size="small"
            value={value}
            onChange={setValue}
            options={options.map(({ value, title, description, icon }) => ({
                value,
                label: <Label icon={icon} title={title} />,
                labelInMenu: <LabelInMenu icon={icon} title={title} description={description} />,
            }))}
            dropdownMatchSelectWidth={false}
            data-attr="funnel-viz-type-select"
        />
    )
}
