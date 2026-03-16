#!/usr/bin/env tsx
// Generates JSON schema from Zod tool-inputs schemas for Python Pydantic schema generation
import * as fs from 'node:fs'
import * as path from 'node:path'
import { z } from 'zod'

import * as schemas from '../src/schema/tool-inputs'

const outputPath = path.join(__dirname, '../schema/tool-inputs.json')

try {
    // Convert all Zod schemas to JSON Schema
    const jsonSchemas = {
        $schema: 'http://json-schema.org/draft-07/schema#',
        definitions: {} as Record<string, any>,
    }

    // Add each schema to the definitions
    for (const [schemaName, zodSchema] of Object.entries(schemas)) {
        if (schemaName.endsWith('Schema')) {
            const jsonSchema = z.toJSONSchema(zodSchema as z.ZodType, {
                reused: 'inline',
                io: 'input',
            })

            // Remove the top-level $schema to avoid conflicts
            delete (jsonSchema as any).$schema

            jsonSchemas.definitions[schemaName] = jsonSchema
        }
    }

    // Write the combined schema
    const schemaString = JSON.stringify(jsonSchemas, null, 2)
    fs.writeFileSync(outputPath, schemaString)
} catch (err) {
    console.error('❌ Error generating schema:', err)
    process.exit(1)
}
