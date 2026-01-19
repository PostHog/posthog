import { useValues } from 'kea'

import { IconCode } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

import { PropertyFilterType } from '~/types'

import { workflowLogic } from '../../workflowLogic'

export const HogFlowTaxonomicFilters = ({
    onChange,
}: {
    onChange: (value: TaxonomicFilterValue, item: any) => void
}): JSX.Element => {
    const { workflow } = useValues(workflowLogic)
    const variables = workflow?.variables || []

    if (!variables.length) {
        return <div className="p-2 text-muted">No workflow variables defined.</div>
    }

    return (
        <div className="flex flex-col gap-2 p-2">
            {variables.map((variable: any) => (
                <LemonButton
                    key={variable.key || variable.name}
                    size="small"
                    fullWidth
                    icon={<IconCode />}
                    onClick={() =>
                        onChange(variable.key, {
                            key: variable.key,
                            name: variable.key,
                            propertyFilterType: PropertyFilterType.WorkflowVariable,
                            taxonomicFilterGroup: TaxonomicFilterGroupType.WorkflowVariables,
                        })
                    }
                >
                    {variable.key}
                </LemonButton>
            ))}
        </div>
    )
}
