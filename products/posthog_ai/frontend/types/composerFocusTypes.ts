import type { QuerySchema } from '~/queries/schema/schema-general'

/**
 * What a host pins above the composer: the thing the user is asking about. The host describes it as
 * data and the surface owns the rendering, so a host never hands a React node into the panel.
 */
export interface ComposerFocus {
    /** Stable id of the focused thing, e.g. a notebook cell's node id. */
    id: string
    title: string
    /** One line under the title that tells the user what the agent can see. */
    caption?: string
    /** Rendered as a read-only chart. Takes precedence over `code`. */
    query?: QuerySchema | null
    /** Rendered as a read-only code block when there is no `query`. */
    code?: string | null
    codeLanguage?: 'sql' | 'python'
    /** Where the "Open" button goes. The button is hidden without it. */
    openUrl?: string | null
    /**
     * The attached context group this focus belongs to. Closing the card dismisses the group, so the
     * card and its chips leave together.
     */
    dismissGroup?: string
}

export interface RegisteredComposerFocus extends ComposerFocus {
    providerId: string
}
