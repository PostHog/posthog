import { useActions } from 'kea'
import { useCallback } from 'react'

import { LemonButton } from '@posthog/lemon-ui'
import { Button, Text } from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'

import {
    AssigneeIconDisplay,
    AssigneeLabelDisplay,
    AssigneeResolver,
} from '../../../components/Assignee/AssigneeDisplay'
import { assigneeSelectLogic } from '../../../components/Assignee/assigneeSelectLogic'
import { QuillAssigneeIconDisplay } from '../../../components/Assignee/QuillAssigneeIconDisplay'
import { QuillAssigneeLabelDisplay } from '../../../components/Assignee/QuillAssigneeLabelDisplay'
import { errorTrackingEditAccessDisabledReason } from '../../../utils'
import { RuleList } from '../rules/RuleList'
import { ErrorTrackingAssignmentRule, ErrorTrackingRuleType } from '../rules/types'
import { AssignmentRuleModal } from './AssignmentRuleModal'
import { assignmentRuleModalLogic } from './assignmentRuleModalLogic'
import { CodeOwnersModal } from './CodeOwnersModal'
import { codeOwnersModalLogic } from './codeOwnersModalLogic'
import { QuillCodeOwnersModal } from './QuillCodeOwnersModal'

export function AssignmentRules(): JSX.Element {
    const { ensureAssigneeTypesLoaded } = useActions(assigneeSelectLogic)
    const { openModal: openCodeOwnersModal } = useActions(codeOwnersModalLogic)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

    const onMount = useCallback(() => {
        ensureAssigneeTypesLoaded()
    }, [ensureAssigneeTypesLoaded])

    const description =
        'Automatically assign newly created issues based on properties of the exception event the first time it was seen. The first rule that matches will be applied.'

    return (
        <RuleList
            ruleType={ErrorTrackingRuleType.Assignment}
            modalLogic={assignmentRuleModalLogic}
            modal={
                <>
                    <AssignmentRuleModal />
                    {todayRailNav ? <QuillCodeOwnersModal /> : <CodeOwnersModal />}
                </>
            }
            taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
            pageKeyPrefix="assignment-rule"
            onMount={onMount}
            headerActions={
                todayRailNav ? (
                    <Button
                        variant="outline"
                        onClick={() => openCodeOwnersModal()}
                        disabledReason={errorTrackingEditAccessDisabledReason() ?? undefined}
                    >
                        Code owners
                    </Button>
                ) : (
                    <LemonButton
                        type="secondary"
                        size="small"
                        onClick={() => openCodeOwnersModal()}
                        disabledReason={errorTrackingEditAccessDisabledReason() ?? undefined}
                    >
                        Code owners
                    </LemonButton>
                )
            }
            description={
                todayRailNav ? (
                    <Text size="xs" render={<p className="m-0" />}>
                        {description}
                    </Text>
                ) : (
                    <p>{description}</p>
                )
            }
            renderCardHeaderExtra={(rule: ErrorTrackingAssignmentRule) => (
                <>
                    <span className={todayRailNav ? 'text-xs text-muted-foreground' : 'text-xs text-muted'}>→</span>
                    <AssigneeResolver assignee={rule.assignee}>
                        {({ assignee }) =>
                            todayRailNav ? (
                                <span className="flex items-center gap-1">
                                    <QuillAssigneeIconDisplay assignee={assignee} size="xsmall" />
                                    <QuillAssigneeLabelDisplay assignee={assignee} />
                                </span>
                            ) : (
                                <span className="flex items-center gap-1 text-xs">
                                    <AssigneeIconDisplay assignee={assignee} size="xsmall" />
                                    <AssigneeLabelDisplay assignee={assignee} />
                                </span>
                            )
                        }
                    </AssigneeResolver>
                </>
            )}
        />
    )
}
