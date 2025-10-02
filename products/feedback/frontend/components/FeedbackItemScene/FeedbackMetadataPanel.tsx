import { useActions, useValues } from 'kea'

import { MemberSelect } from 'lib/components/MemberSelect'
import { SceneCommonButtons } from 'lib/components/Scenes/SceneCommonButtons'
import { SceneActivityIndicator } from 'lib/components/Scenes/SceneUpdateActivityInfo'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuOpenIndicator,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { copyToClipboard } from 'lib/utils/copyToClipboard'

import { ScenePanelCommonActions, ScenePanelDivider, ScenePanelLabel } from '~/layout/scenes/SceneLayout'

import { feedbackItemSceneLogic } from '../../scenes/FeedbackItemScene/feedbackItemSceneLogic'
import { feedbackGeneralSettingsLogic } from '../../settings/feedbackGeneralSettingsLogic'

const RESOURCE_TYPE = 'feedback'

export function FeedbackMetadataPanel(): JSX.Element | null {
    const { feedbackItem, feedbackItemLoading } = useValues(feedbackItemSceneLogic)
    const { feedbackCategories, feedbackTopics, getStatusesForCategory } = useValues(feedbackGeneralSettingsLogic)
    const { updateStatus, updateAssignment, updateCategory, updateTopic } = useActions(feedbackItemSceneLogic)

    if (feedbackItemLoading && !feedbackItem) {
        return null
    }

    return (
        <div className="flex flex-col gap-2">
            <ScenePanelLabel title="Feedback ID">{feedbackItem?.id}</ScenePanelLabel>

            <ScenePanelLabel title="Category">
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive fullWidth className="flex justify-between" variant="panel" menuItem>
                            <span>{feedbackItem?.category?.name ?? 'Select category'}</span>
                            <DropdownMenuOpenIndicator />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent loop matchTriggerWidth>
                        {feedbackCategories.map((category) => (
                            <DropdownMenuItem key={category.id} asChild>
                                <ButtonPrimitive menuItem onClick={() => updateCategory(category.id)}>
                                    {category.name}
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            </ScenePanelLabel>

            <ScenePanelLabel title="Status">
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive
                            fullWidth
                            className="flex justify-between"
                            variant="panel"
                            menuItem
                            disabled={!feedbackItem?.category}
                        >
                            <span>{feedbackItem?.status?.name ?? 'Select status'}</span>
                            {feedbackItem?.category && <DropdownMenuOpenIndicator />}
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent loop matchTriggerWidth>
                        {feedbackItem?.category?.id &&
                            getStatusesForCategory(feedbackItem.category.id).map((status) => (
                                <DropdownMenuItem key={status.id} asChild>
                                    <ButtonPrimitive menuItem onClick={() => updateStatus(status.id)}>
                                        {status.name}
                                    </ButtonPrimitive>
                                </DropdownMenuItem>
                            ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            </ScenePanelLabel>

            <ScenePanelLabel title="Topic">
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <ButtonPrimitive fullWidth className="flex justify-between" variant="panel" menuItem>
                            <span>{feedbackItem?.topic?.name ?? 'Select topic'}</span>
                            <DropdownMenuOpenIndicator />
                        </ButtonPrimitive>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent loop matchTriggerWidth>
                        {feedbackTopics.map((topic) => (
                            <DropdownMenuItem key={topic.id} asChild>
                                <ButtonPrimitive menuItem onClick={() => updateTopic(topic.id)}>
                                    {topic.name}
                                </ButtonPrimitive>
                            </DropdownMenuItem>
                        ))}
                    </DropdownMenuContent>
                </DropdownMenu>
            </ScenePanelLabel>

            <ScenePanelLabel title="Assigned to">
                <MemberSelect
                    value={feedbackItem?.assignment?.user?.id ?? null}
                    onChange={(user) => updateAssignment(user?.id ?? null)}
                    defaultLabel="Unassigned"
                    allowNone={true}
                    type="secondary"
                    size="small"
                />
            </ScenePanelLabel>

            <SceneActivityIndicator at={feedbackItem?.created_at} prefix="Created" />

            <ScenePanelDivider />

            <ScenePanelCommonActions>
                <SceneCommonButtons
                    comment
                    share={{
                        onClick: () => {
                            void copyToClipboard(window.location.href, 'feedback link')
                        },
                    }}
                    dataAttrKey={RESOURCE_TYPE}
                />
            </ScenePanelCommonActions>
        </div>
    )
}
