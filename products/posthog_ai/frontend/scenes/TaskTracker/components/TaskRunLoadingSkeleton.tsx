import { useState } from 'react'

import { QuillRunSurfaceInputs } from '../../../components/quill/QuillRunSurfaceInputs'
import { RunLogSkeleton } from '../../../components/RunLogSkeleton'
import { useThreadSkin } from '../../../hooks/useThreadSkin'
import { QuillTaskComposerSkeleton } from './QuillTaskComposerSkeleton'

export function TaskRunLoadingSkeleton(): JSX.Element {
    const skin = useThreadSkin()
    const [inputsHeight, setInputsHeight] = useState(0)
    if (skin === 'lemon') {
        return <RunLogSkeleton />
    }
    return (
        <div className="@container/thread flex h-full min-h-0 flex-col">
            <RunLogSkeleton className="flex-1" listClassName="py-4" rowClassName="px-4" />
            <QuillRunSurfaceInputs
                approval={null}
                showApproval={false}
                composer={<QuillTaskComposerSkeleton />}
                height={inputsHeight}
                onHeightChange={setInputsHeight}
            />
        </div>
    )
}
