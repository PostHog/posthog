import { normalizeParamAliases } from '@/tools/cast-helpers'

/**
 * How every notebook tool documents its notebook identifier.
 *
 * It names `notebooks-list` because a caller that omits the parameter usually
 * never held the id, and it rules out the UUID because that is the other value
 * a notebook record carries under a name that reads like an identifier.
 */
export const NOTEBOOK_SHORT_ID_DESCRIPTION =
    "The notebook's short_id, the short alphanumeric id in its URL (e.g. `aBcD1234`) that `notebooks-list` returns; not the notebook's UUID `id`."

/** Every spelling the notebook tools use for the identifier between them. */
const NOTEBOOK_ID_SPELLINGS = ['short_id', 'notebook_id', 'notebookId', 'shortId', 'notebook_short_id']

/**
 * Accepts the other notebook tools' spelling of the identifier and normalizes it
 * to this tool's own. The CRUD tools name it `short_id` and the cell tools name
 * it `notebook_id`, so a caller that learned one spelling was rejected by the
 * other. Compose with `z.preprocess(notebookIdAliases('notebook_id'), schema)`.
 */
export const notebookIdAliases = (canonical: string): ((input: unknown) => unknown) =>
    normalizeParamAliases({ [canonical]: NOTEBOOK_ID_SPELLINGS.filter((name) => name !== canonical) })
