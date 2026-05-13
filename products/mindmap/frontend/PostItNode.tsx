import { Handle, Position } from '@xyflow/react'
import { router } from 'kea-router'

import { urls } from 'scenes/urls'

const COLOR_TO_CLASS: Record<string, string> = {
    yellow: 'bg-yellow-200',
    pink: 'bg-pink-200',
    blue: 'bg-blue-200',
    green: 'bg-green-200',
    purple: 'bg-purple-200',
    orange: 'bg-orange-200',
    gray: 'bg-gray-200',
}

export interface PostItNodeData {
    short_id: string
    title: string
    body: string
    color: string
    emoji: string
    notebook_short_id: string | null
}

export function PostItNode({ data }: { data: PostItNodeData }): JSX.Element {
    const handleClick = (): void => {
        if (data.notebook_short_id) {
            router.actions.push(urls.notebook(data.notebook_short_id))
        }
    }

    const bgClass = COLOR_TO_CLASS[data.color] ?? COLOR_TO_CLASS.yellow

    return (
        <div
            className={`PostItNode ${bgClass} rounded-md shadow-md p-3 w-48 cursor-pointer select-none`}
            onClick={handleClick}
            data-attr={`postit-${data.short_id}`}
        >
            <Handle type="target" position={Position.Top} />
            <div className="flex items-center gap-2">
                {data.emoji ? <span className="text-base">{data.emoji}</span> : null}
                <span className="font-semibold text-sm truncate flex-1">{data.title}</span>
                {data.notebook_short_id ? <span title="Linked notebook">🗒</span> : null}
            </div>
            {data.body ? <p className="text-xs mt-1 line-clamp-2 text-gray-700">{data.body}</p> : null}
            <Handle type="source" position={Position.Bottom} />
        </div>
    )
}
