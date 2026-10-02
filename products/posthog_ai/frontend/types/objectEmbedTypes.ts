import type { ComponentType, LazyExoticComponent } from 'react'

export interface ObjectEmbedProps {
    /** The object id exactly as the agent cited it, for example a survey uuid or an experiment id. */
    objectId: string
}

/**
 * A read-only live view of one PostHog object kind, which the task artifacts pane shows when the agent cites an object.
 * The product that owns the kind declares the entry, so this surface never imports that product's internals.
 */
export interface ObjectEmbedEntry {
    /** An object tag kind from `posthog/object_tags/kinds.py`, for example 'experiment'. */
    kind: string
    Embed: ComponentType<ObjectEmbedProps> | LazyExoticComponent<ComponentType<ObjectEmbedProps>>
}
