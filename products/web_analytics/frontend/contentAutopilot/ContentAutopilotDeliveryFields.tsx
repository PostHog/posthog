import { useActions } from 'kea'

import { LemonInput, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { LemonField } from 'lib/lemon-ui/LemonField'

import type { ContentAutopilotProfileDraft } from './contentAutopilotLogic'
import { contentAutopilotLogic } from './contentAutopilotLogic'

export const ContentAutopilotDeliveryFields = ({ draft }: { draft: ContentAutopilotProfileDraft }): JSX.Element => {
    const { setProfileDraft } = useActions(contentAutopilotLogic)
    const isGitHub = draft.deliveryMode === 'github'

    return (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <LemonField.Pure label="Brand rules" help="One terminology or editorial rule per line.">
                <LemonTextArea
                    value={draft.brandRules}
                    onChange={(brandRules) => setProfileDraft({ brandRules })}
                    placeholder="Use sentence case for headings"
                    minRows={3}
                />
            </LemonField.Pure>
            <LemonField.Pure label="Delivery">
                <LemonSelect
                    value={draft.deliveryMode}
                    onChange={(deliveryMode) => setProfileDraft({ deliveryMode })}
                    options={[
                        { value: 'export_only', label: 'Markdown export' },
                        { value: 'github', label: 'GitHub pull request' },
                    ]}
                    fullWidth
                />
            </LemonField.Pure>
            {isGitHub ? (
                <>
                    <LemonField.Pure label="GitHub repository">
                        <LemonInput
                            value={draft.githubRepository}
                            onChange={(githubRepository) => setProfileDraft({ githubRepository })}
                            placeholder="owner/repository"
                            fullWidth
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Base branch">
                        <LemonInput
                            value={draft.baseBranch}
                            onChange={(baseBranch) => setProfileDraft({ baseBranch })}
                            placeholder="main"
                            fullWidth
                        />
                    </LemonField.Pure>
                    <LemonField.Pure label="Content directories" help="One repository-relative directory per line.">
                        <LemonTextArea
                            value={draft.contentDirectories}
                            onChange={(contentDirectories) => setProfileDraft({ contentDirectories })}
                            placeholder="contents/docs"
                            minRows={2}
                        />
                    </LemonField.Pure>
                    <LemonField.Pure
                        label="URL-to-file convention"
                        help="Describe how public URLs map to repository files."
                    >
                        <LemonTextArea
                            value={draft.urlToFileConvention}
                            onChange={(urlToFileConvention) => setProfileDraft({ urlToFileConvention })}
                            placeholder="/docs/topic maps to contents/docs/topic.mdx"
                            minRows={2}
                        />
                    </LemonField.Pure>
                </>
            ) : null}
        </div>
    )
}
