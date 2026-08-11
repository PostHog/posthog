import { useState } from 'react'

import { LemonInput, LemonTag } from '@posthog/lemon-ui'

import type {
    PatchedSignalScoutConfigUpdateApi as SignalScoutConfigUpdate,
    SignalScoutConfigApi as SignalScoutConfig,
} from 'products/signals/frontend/generated/api.schemas'

import {
    MAX_SCOUT_TAG_LENGTH,
    MAX_SCOUT_TAGS,
    parseScoutTagsInput,
    scoutTags,
    withScoutTagRemoved,
    withScoutTagsAdded,
} from '../../../utils/scoutTags'

export function ScoutTagsEditor({
    config,
    onUpdate,
    updating = false,
}: {
    config: SignalScoutConfig
    onUpdate: (configId: string, updates: SignalScoutConfigUpdate) => void
    updating?: boolean
}): JSX.Element {
    const [draft, setDraft] = useState('')
    const [error, setError] = useState<string | null>(null)
    const tags = scoutTags(config)
    const atCap = tags.length >= MAX_SCOUT_TAGS

    const commitDraft = (): void => {
        const parsed = parseScoutTagsInput(draft)
        if (parsed.tooLong.length > 0) {
            setError(`Tags can be up to ${MAX_SCOUT_TAG_LENGTH} characters.`)
            return
        }
        const added = withScoutTagsAdded(tags, parsed.tags)
        if (added.overCap) {
            setError(`A scout can have up to ${MAX_SCOUT_TAGS} tags.`)
            return
        }
        setError(null)
        setDraft('')
        if (added.tags) {
            onUpdate(config.id, { tags: added.tags })
        }
    }

    const removeTag = (tag: string): void => {
        if (updating) {
            return
        }
        const nextTags = withScoutTagRemoved(tags, tag)
        if (nextTags) {
            onUpdate(config.id, { tags: nextTags })
        }
    }

    return (
        <div className="flex flex-col gap-1">
            <div className="flex flex-wrap items-center gap-1">
                {tags.map((tag) => (
                    <LemonTag
                        key={tag}
                        type="highlight"
                        size="small"
                        closable={!updating}
                        onClose={() => removeTag(tag)}
                    >
                        {tag}
                    </LemonTag>
                ))}
                <LemonInput
                    value={draft}
                    onChange={(value) => {
                        setDraft(value)
                        setError(null)
                    }}
                    onBlur={commitDraft}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter' || event.key === ',') {
                            event.preventDefault()
                            commitDraft()
                        } else if (event.key === 'Backspace' && draft === '' && tags.length > 0) {
                            event.preventDefault()
                            removeTag(tags[tags.length - 1])
                        }
                    }}
                    size="xsmall"
                    placeholder={atCap ? `${MAX_SCOUT_TAGS} tag limit` : 'Add tag'}
                    aria-label={`${config.skill_name} tags`}
                    disabledReason={
                        updating
                            ? 'Saving scout settings'
                            : atCap
                              ? `A scout can have up to ${MAX_SCOUT_TAGS} tags`
                              : undefined
                    }
                    status={error ? 'danger' : 'default'}
                    className="w-40"
                />
            </div>
            {error ? (
                <span role="alert" className="text-xs text-danger">
                    {error}
                </span>
            ) : null}
        </div>
    )
}
