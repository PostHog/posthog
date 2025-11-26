import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilterGroupType, TaxonomicFilterValue } from 'lib/components/TaxonomicFilter/types'

import { CyclotronJobInputSchemaType, PropertyFilterType } from '~/types'

import { workflowLogic } from '../../workflowLogic'

export const HogFlowTaxonomicFilters = ({
    onChange,
}: {
    onChange: (value: TaxonomicFilterValue, item: any) => void
}): JSX.Element => {
    const logic = workflowLogic.findMounted()
    let variables: CyclotronJobInputSchemaType[] = []

    if (logic) {
        variables = logic.values.workflow?.variables || []
    }

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
                    onClick={() =>
                        onChange(`variables.${variable.key}`, {
                            key: `variables.${variable.key}`,
                            name: variable.key,
                            propertyFilterType: PropertyFilterType.WorkflowVariable,
                            taxonomicFilterGroup: TaxonomicFilterGroupType.WorkflowVariables,
                        })
                    }
                >
                    {variable.name || variable.key}
                </LemonButton>
            ))}
        </div>
    )
}
