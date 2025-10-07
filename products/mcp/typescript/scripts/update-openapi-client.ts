#!/usr/bin/env tsx

import { execSync } from 'node:child_process'
import * as fs from 'node:fs'

const SCHEMA_URL = 'https://app.posthog.com/api/schema/'
const TEMP_SCHEMA_PATH = 'temp-openapi.yaml'
const OUTPUT_PATH = 'src/api/generated.ts'

async function fetchSchema() {
    console.log('Fetching OpenAPI schema from PostHog API...')

    try {
        const response = await fetch(SCHEMA_URL)
        if (!response.ok) {
            throw new Error(`Failed to fetch schema: ${response.status} ${response.statusText}`)
        }

        const schema = await response.text()
        fs.writeFileSync(TEMP_SCHEMA_PATH, schema, 'utf-8')
        console.log(`✓ Schema saved to ${TEMP_SCHEMA_PATH}`)

        return true
    } catch (error) {
        console.error('Error fetching schema:', error)
        return false
    }
}

function generateClient() {
    console.log('Generating TypeScript client...')

    try {
        execSync(`pnpm typed-openapi ${TEMP_SCHEMA_PATH} --output ${OUTPUT_PATH}`, {
            stdio: 'inherit',
        })
        console.log(`✓ Client generated at ${OUTPUT_PATH}`)
        return true
    } catch (error) {
        console.error('Error generating client:', error)
        return false
    }
}

function cleanup() {
    try {
        if (fs.existsSync(TEMP_SCHEMA_PATH)) {
            fs.unlinkSync(TEMP_SCHEMA_PATH)
            console.log('✓ Cleaned up temporary schema file')
        }
    } catch (error) {
        console.error('Warning: Could not clean up temporary file:', error)
    }
}

async function main() {
    console.log('Starting OpenAPI client update...\n')

    const schemaFetched = await fetchSchema()
    if (!schemaFetched) {
        process.exit(1)
    }

    const clientGenerated = generateClient()

    cleanup()

    if (!clientGenerated) {
        process.exit(1)
    }

    console.log('\n✅ OpenAPI client successfully updated!')
}

main().catch((error) => {
    console.error('Unexpected error:', error)
    process.exit(1)
})
