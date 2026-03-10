import { useActions } from 'kea'
import { useCallback } from 'react'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import {
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    AssigneeResolver,
} from '../../../components/Assignee/AssigneeDisplay'
import { assigneeSelectLogic } from '../../../components/Assignee/assigneeSelectLogic'
import { RuleList } from '../rules/RuleList'
import { ErrorTrackingAssignmentRule, ErrorTrackingRuleType } from '../rules/types'
import { AssignmentRuleModal } from './AssignmentRuleModal'
import { assignmentRuleModalLogic } from './assignmentRuleModalLogic'

export function AssignmentRules(): JSX.Element {
    const { ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)

    const onMount = useCallback(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    return (
        <RuleList
            ruleType={ErrorTrackingRuleType.Assignment}
            modalLogic={assignmentRuleModalLogic}
            modal={<AssignmentRuleModal />}
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            pageKeyPrefix="assignment-rule"
            onMount={onMount}
            description={
                <p>
                    Automatically assign newly created issues based on properties of the exception event the first time
                    it was seen. The first rule that matches will be applied.
                </p>
            }
            renderCardHeaderExtra={(rule: ErrorTrackingAssignmentRule) => (
                <>
                    <span className="text-xs text-muted">→</span>
                    <AssigneeResolver assignee={rule.assignee}>
                        {({ assignee }) => (
                            <span className="flex items-center gap-1 text-xs">
                                <AssigneeIconDisplay assignee={assignee} size="xsmall" />
                                <AssigneeLabelDisplay assignee={assignee} />
                            </span>
                        )}
                    </AssigneeResolver>
                </>
            )}
        />
    )
}
