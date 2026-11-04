import { TZLabel } from 'lib/components/TZLabel'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'

import type { StoryAuthor } from './explainChartLogic'

export function ExplainChartByline({ author }: { author: StoryAuthor }): JSX.Element {
    return (
        <div className="flex items-center gap-1.5 px-2 pt-2 text-xs text-secondary">
            <span>Explained</span>
            {author.createdBy && (
                <>
                    <span>by</span>
                    <ProfilePicture user={author.createdBy} showName size="sm" />
                </>
            )}
            <TZLabel time={author.createdAt} />
        </div>
    )
}
