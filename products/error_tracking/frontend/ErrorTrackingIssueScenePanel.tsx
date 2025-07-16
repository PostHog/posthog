import { SceneName } from 'lib/components/Scenes/SceneName'
import { useActions, useValues } from 'kea'
import {
    ScenePanel,
    ScenePanelActions,
    ScenePanelCommonActions,
    ScenePanelDivider,
    ScenePanelMetaInfo,
} from '~/layout/scenes/SceneLayout'
import { errorTrackingIssueSceneLogic } from './errorTrackingIssueSceneLogic'
import { SceneDescription } from 'lib/components/Scenes/SceneDescription'
import { SceneCommonButtons } from 'lib/components/Scenes/SceneCommonButtons'

export const ErrorTrackingIssueScenePanel = (): JSX.Element | null => {
    const { issue } = useValues(errorTrackingIssueSceneLogic)
    const { updateName, updateDescription } = useActions(errorTrackingIssueSceneLogic)

    return issue ? (
        <ScenePanel>
            <ScenePanelMetaInfo>
                <SceneName defaultValue={issue.name ?? ''} onSave={updateName} dataAttr="issue-name" />

                <SceneDescription
                    defaultValue={issue.description ?? ''}
                    onSave={updateDescription}
                    dataAttr="insight-description"
                />
                {/* <SceneFile />
                <SceneActivityIndicator
                    at={insight.last_modified_at}
                    by={insight.last_modified_by}
                    prefix="Last modified"
                /> */}
            </ScenePanelMetaInfo>

            <ScenePanelDivider />

            <ScenePanelCommonActions>
                <SceneCommonButtons comment share={{ onClick: () => {} }} />
            </ScenePanelCommonActions>

            <ScenePanelActions>
                <div>Hello</div>
                {/* {hasDashboardItemId && (
                    <SceneShareButton
                        buttonProps={{
                            menuItem: true,
                            onClick: () => (insight.short_id ? push(urls.insightSharing(insight.short_id)) : null),
                        }}
                    >
                        <IconShare />
                        Share or embed
                    </SceneShareButton>
                )} */}
            </ScenePanelActions>
        </ScenePanel>
    ) : null
}
