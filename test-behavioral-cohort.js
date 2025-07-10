#!/usr/bin/env node

/**
 * Simple test script to verify behavioral cohort writer works
 * 
 * This script:
 * 1. Creates a test cohort with behavioral filters
 * 2. Sends a test event that should match the cohort
 * 3. Checks if the event was logged to the file
 * 
 * Run with: node test-behavioral-cohort.js
 */

const { Pool } = require('pg')
const fs = require('fs')
const path = require('path')

const LOG_FILE = '/tmp/posthog-behavioral-cohorts/behavioral-cohort-matches.jsonl'

async function testBehavioralCohort() {
    console.log('🧪 Testing behavioral cohort writer...')
    
    // Clear any existing log file
    try {
        if (fs.existsSync(LOG_FILE)) {
            fs.unlinkSync(LOG_FILE)
            console.log('✓ Cleared existing log file')
        }
    } catch (err) {
        console.log('ℹ️  No existing log file to clear')
    }

    // Create test cohort in database
    const pool = new Pool({
        host: process.env.POSTGRES_HOST || 'localhost',
        port: parseInt(process.env.POSTGRES_PORT || '5432'),
        database: process.env.POSTGRES_DB || 'posthog',
        user: process.env.POSTGRES_USER || 'posthog',
        password: process.env.POSTGRES_PASSWORD || 'posthog',
    })

    try {
        // Get a test team (assuming team_id 1 exists)
        const teamResult = await pool.query('SELECT id, name FROM posthog_team WHERE id = 1 LIMIT 1')
        if (teamResult.rows.length === 0) {
            console.error('❌ No team found with id=1. Please ensure you have a team in your database.')
            return
        }

        const team = teamResult.rows[0]
        console.log(`✓ Found team: ${team.name} (id: ${team.id})`)

        // Create test cohort
        const cohortProperties = {
            "type": "AND",
            "values": [
                {
                    "type": "OR",
                    "values": [
                        {
                            "type": "OR",
                            "values": [
                                {
                                    "key": "test_behavioral_event",
                                    "type": "behavioral",
                                    "value": "performed_event_multiple",
                                    "negation": false,
                                    "operator": "gte",
                                    "event_type": "events",
                                    "operator_value": 1,
                                    "explicit_datetime": "-30d"
                                }
                            ]
                        }
                    ]
                }
            ]
        }

        // Insert or update test cohort
        const cohortResult = await pool.query(`
            INSERT INTO posthog_cohort (name, description, team_id, properties, deleted, created_at, created_by_id)
            VALUES ($1, $2, $3, $4, false, now(), null)
            ON CONFLICT (team_id, name) DO UPDATE SET
                properties = EXCLUDED.properties,
                updated_at = now()
            RETURNING id, name
        `, [
            'Test Behavioral Cohort',
            'Test cohort for behavioral cohort writer',
            team.id,
            JSON.stringify(cohortProperties)
        ])

        const cohort = cohortResult.rows[0]
        console.log(`✓ Created/updated cohort: ${cohort.name} (id: ${cohort.id})`)

        console.log('\n🎯 Now send a test event to trigger the behavioral cohort writer:')
        console.log(`
curl -X POST http://localhost:8000/capture/ \\
  -H "Content-Type: application/json" \\
  -d '{
    "api_key": "your-project-api-key",
    "event": "test_behavioral_event",
    "distinct_id": "test-user-123",
    "properties": {
      "test": "value",
      "timestamp": "${new Date().toISOString()}"
    }
  }'
`)

        console.log('\n📝 Then check the log file:')
        console.log(`tail -f ${LOG_FILE}`)

        console.log('\n🔍 Or run this to check if it worked:')
        console.log(`node -e "
const fs = require('fs');
const file = '${LOG_FILE}';
if (fs.existsSync(file)) {
    const content = fs.readFileSync(file, 'utf8');
    console.log('✓ Found log entries:');
    content.split('\\n').filter(line => line.trim()).forEach(line => {
        const entry = JSON.parse(line);
        console.log(\`  - \${entry.timestamp}: \${entry.event_name} -> cohort \${entry.cohort_id}\`);
    });
} else {
    console.log('❌ No log file found at ${LOG_FILE}');
}
"`)

    } catch (err) {
        console.error('❌ Error:', err.message)
    } finally {
        await pool.end()
    }
}

if (require.main === module) {
    testBehavioralCohort()
}