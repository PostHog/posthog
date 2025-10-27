#!/usr/bin/env tsx

// Generates JSON schema from Zod tool-inputs schemas for Python Pydantic schema generation

import * as fs from 'node:fs'
import * as path from 'node:path'
import { zodToJsonSchema } from 'zod-to-json-schema'
import * as schemas from '../src/schema/tool-inputs'

const outputPath = path.join(__dirname, '../../schema/tool-inputs.json')

try {
    // Convert all Zod schemas to JSON Schema
    const jsonSchemas = {
        $schema: 'http://json-schema.org/draft-07/schema#',
        definitions: {} as Record<string, any>,
    }

    // Add each schema to the definitions
    for (const [schemaName, zodSchema] of Object.entries(schemas)) {
        if (schemaName.endsWith('Schema')) {
            const jsonSchema = zodToJsonSchema(zodSchema, {
                name: schemaName,
                $refStrategy: 'none',
            })

            // Remove the top-level $schema to avoid conflicts
            jsonSchema.$schema = undefined

            // Extract the actual schema from nested definitions if present
            let actualSchema = jsonSchema
            const schemaObj = jsonSchema as any

            // If there's nested definitions with the schema name, use that
            if (schemaObj.definitions?.[schemaName]) {
                actualSchema = schemaObj.definitions[schemaName]
            }
            // If there's a $ref pointing to itself, and definitions exist, extract the definition
            else if (schemaObj.$ref?.includes(schemaName) && schemaObj.definitions) {
                actualSchema = schemaObj.definitions[schemaName] || schemaObj
            }

            // Clean up any remaining $schema references
            if (actualSchema.$schema) {
                actualSchema.$schema = undefined
            }

            jsonSchemas.definitions[schemaName] = actualSchema
        }
    }

    // Write the combined schema
    const schemaString = JSON.stringify(jsonSchemas, null, 2)
    fs.writeFileSync(outputPath, schemaString)
} catch (err) {
    console.error('❌ Error generating schema:', err)
    process.exit(1)
}
