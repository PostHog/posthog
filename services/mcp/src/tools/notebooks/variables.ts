import { z } from 'zod'

import { DATAFRAME_NAME_REGEX } from './cellTags'

/** Mirrors MAX_VARIABLES_PER_NOTEBOOK in sql_v2_serializers.py, so the schema stops at the server's limit. */
export const MAX_NOTEBOOK_VARIABLES = 10

/** One notebook variable, shared by every tool that declares or binds them. */
export const NotebookVariableSchema = z
    .object({
        name: z
            .string()
            .regex(DATAFRAME_NAME_REGEX)
            .describe(
                "Identifier cells read: `{name}` in a SQL cell, a plain global in a Python cell. Letters, numbers, and underscores; must not start with a number, repeat another variable, or reuse a cell's dataframe_name."
            ),
        type: z
            .enum(['string', 'number', 'boolean', 'date'])
            .describe(
                "How the value binds: 'string', 'number', 'boolean', or 'date'. A 'date' is an absolute ISO 8601 date or datetime ('2025-01-31', '2025-01-31T09:00:00Z'); relative expressions like '-7d' are rejected, so compute the date first."
            ),
        value: z
            .union([z.string(), z.number(), z.boolean(), z.null()])
            .optional()
            .describe('The current value. Omit or pass null for a declared-but-unset variable.'),
    })
    .strict()

export type NotebookVariableInput = z.infer<typeof NotebookVariableSchema>

/** Names whose declaration is repeated. A Python cell binds them into one namespace, so a repeat is ambiguous. */
export function duplicateVariableNames(variables: { name: string }[]): string[] {
    const names = variables.map((variable) => variable.name)
    return [...new Set(names.filter((name, index) => names.indexOf(name) !== index))]
}
