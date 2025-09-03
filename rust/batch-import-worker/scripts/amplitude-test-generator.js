#!/usr/bin/env node

/**
 * Amplitude Test Data Generator
 *
 * This script generates comprehensive test data for the PostHog Amplitude identify logic.
 * It creates various scenarios to test:
 * - First-time user-device combinations (should generate identify events)
 * - Duplicate user-device combinations (should NOT generate duplicate identify events)
 * - Multi-device users, multi-user devices
 * - Edge cases with special characters, unicode, etc.
 * - Cross-session scenarios and anonymous->identified transitions
 */

const amplitude = require('@amplitude/analytics-node');

function showHelp() {
    console.log(`
Amplitude Test Data Generator

Usage: node amplitude-test-generator.js

Environment Variables:
  AMPLITUDE_API_KEY           Your Amplitude API key (required for sending)
  AMPLITUDE_CLUSTER           Cluster: 'us' (default) or 'eu'
  AMPLITUDE_START_TIME        Start timestamp for events (ISO format or relative)
                              Examples: '2024-01-01T00:00:00Z', '2024-01-01', '1 week ago'
  AMPLITUDE_END_TIME          End timestamp for events (ISO format or relative)
                              Examples: '2024-01-07T23:59:59Z', '2024-01-07', 'now'

Examples:
  # Generate events for a specific week
  AMPLITUDE_START_TIME='2024-01-01T00:00:00Z' AMPLITUDE_END_TIME='2024-01-07T23:59:59Z' node amplitude-test-generator.js

  # Generate events using relative dates
  AMPLITUDE_START_TIME='1 week ago' AMPLITUDE_END_TIME='now' node amplitude-test-generator.js

  # Generate events for a specific day
  AMPLITUDE_START_TIME='2024-01-15' AMPLITUDE_END_TIME='2024-01-15T23:59:59Z' node amplitude-test-generator.js
`);
}

function parseTimestamp(input) {
    if (!input) return null;

    // Handle relative timestamps
    if (input === 'now') {
        return new Date();
    }

    // Handle "X time ago" format
    const relativeMatch = input.match(/^(\d+)\s+(minute|hour|day|week|month|year)s?\s+ago$/i);
    if (relativeMatch) {
        const amount = parseInt(relativeMatch[1]);
        const unit = relativeMatch[2].toLowerCase();
        const now = new Date();

        switch (unit) {
            case 'minute':
                return new Date(now.getTime() - amount * 60 * 1000);
            case 'hour':
                return new Date(now.getTime() - amount * 60 * 60 * 1000);
            case 'day':
                return new Date(now.getTime() - amount * 24 * 60 * 60 * 1000);
            case 'week':
                return new Date(now.getTime() - amount * 7 * 24 * 60 * 60 * 1000);
            case 'month':
                const monthsAgo = new Date(now);
                monthsAgo.setMonth(monthsAgo.getMonth() - amount);
                return monthsAgo;
            case 'year':
                const yearsAgo = new Date(now);
                yearsAgo.setFullYear(yearsAgo.getFullYear() - amount);
                return yearsAgo;
        }
    }

    // Handle date-only format (add time if missing)
    if (/^\d{4}-\d{2}-\d{2}$/.test(input)) {
        return new Date(input + 'T00:00:00Z');
    }

    // Try parsing as ISO timestamp
    const parsed = new Date(input);
    if (isNaN(parsed.getTime())) {
        throw new Error(`Invalid timestamp format: ${input}`);
    }

    return parsed;
}

// Configuration
const AMPLITUDE_API_KEY = process.env.AMPLITUDE_API_KEY || 'test_amplitude_key';
const AMPLITUDE_CLUSTER = process.env.AMPLITUDE_CLUSTER || 'us'; // 'us' or 'eu'
const AMPLITUDE_START_TIME = process.env.AMPLITUDE_START_TIME;
const AMPLITUDE_END_TIME = process.env.AMPLITUDE_END_TIME;

// Initialize Amplitude
if (AMPLITUDE_API_KEY !== 'test_amplitude_key') {
    const config = {
        serverZone: AMPLITUDE_CLUSTER === 'eu' ? 'EU' : 'US'
    };
    amplitude.init(AMPLITUDE_API_KEY, config);
}

// Scenario-specific naming for easy identification
const SCENARIO_USERS = {
    FIRST_TIME: [
        'first_time_user_alice',
        'first_time_user_bob',
        'first_time_user_charlie',
        'first_time_user_diana',
        'first_time_user_eve'
    ],
    DUPLICATE: [
        'duplicate_user_frank',
        'duplicate_user_grace',
        'duplicate_user_henry'
    ],
    MULTI_DEVICE: 'multi_device_user_sarah',
    MULTI_USER: [
        'shared_device_parent_mom',
        'shared_device_parent_dad',
        'shared_device_child_alice',
        'shared_device_child_bob'
    ],
    EDGE_CASE: [
        'edge_unicode_用户',
        'edge_email_user@test.com',
        'edge_hash_user#123',
        'edge_long_' + 'x'.repeat(50),
        'edge_normal_user',
        'edge_trimmed_user',
        'edge_numeric_12345',
        'edge_camelCase_User'
    ],
    ANONYMOUS: [
        'anon_to_id_user_1',
        'anon_to_id_user_2',
        'anon_to_id_user_3'
    ],
    JOURNEY: 'journey_user_alex',
};

const SCENARIO_DEVICES = {
    FIRST_TIME: [
        'first_time_device_mobile_1',
        'first_time_device_laptop_2',
        'first_time_device_tablet_3',
        'first_time_device_desktop_4',
        'first_time_device_smartwatch_5'
    ],
    DUPLICATE: [
        'duplicate_device_phone_1',
        'duplicate_device_computer_2',
        'duplicate_device_ipad_3'
    ],
    MULTI_DEVICE: [
        'multi_dev_phone_morning',
        'multi_dev_laptop_work',
        'multi_dev_tablet_home',
        'multi_dev_smarttv_living'
    ],
    MULTI_USER: 'shared_family_tablet_main',
    EDGE_CASE: [
        'edge_unicode_设备',
        'edge_colon_device:123:abc',
        'edge_dots_device.with.dots',
        'edge_long_device_' + 'y'.repeat(50),
        'edge_normal_device',
        'edge_trimmed_device',
        'edge_numeric_67890',
        'edge_kebab-case-device'
    ],
    ANONYMOUS: [
        'anon_device_phone_1',
        'anon_device_laptop_2',
        'anon_device_tablet_3'
    ],
    JOURNEY: [
        'journey_phone_commute',
        'journey_laptop_office',
        'journey_phone_lunch',
        'journey_laptop_office_pm',
        'journey_tablet_home',
        'journey_phone_bedtime'
    ]
};

const EVENT_TYPES = [
    'login',
    'purchase',
    'page_view',
    'button_click',
    'app_open',
    'session_start',
    'video_play',
    'search',
    'signup',
    'logout'
];

// Helper functions
function randomChoice(array) {
    return array[Math.floor(Math.random() * array.length)];
}

function generateTimestamp(baseTime, offsetMinutes = 0) {
    return new Date(baseTime.getTime() + offsetMinutes * 60 * 1000);
}

function log(scenario, description, event) {
    console.log(`[${scenario}] ${description}`);
    console.log(`  Event: ${event.event_type}, User: ${event.user_id || 'null'}, Device: ${event.device_id || 'null'}`);
    console.log('');
}

// Test scenario generators
class AmplitudeTestGenerator {
    constructor(startTime = null, endTime = null) {
        // Use provided time range or default to a 24-hour period starting yesterday
        this.baseTime = startTime || new Date(Date.now() - 24 * 60 * 60 * 1000);
        this.endTime = endTime || new Date(this.baseTime.getTime() + 24 * 60 * 60 * 1000);
        this.currentTime = new Date(this.baseTime);
        this.totalDuration = this.endTime.getTime() - this.baseTime.getTime();
        this.events = [];

        console.log(`📅 Time Range: ${this.baseTime.toISOString()} to ${this.endTime.toISOString()}`);
        console.log(`⏱️  Duration: ${Math.round(this.totalDuration / (1000 * 60 * 60))} hours\n`);
    }

    addEvent(eventType, userId, deviceId, properties = {}, offsetMinutes = 0) {
        let timestamp = generateTimestamp(this.currentTime, offsetMinutes);

        // Ensure timestamp stays within bounds
        if (timestamp.getTime() > this.endTime.getTime()) {
            timestamp = this.endTime;
        }
        if (timestamp.getTime() < this.baseTime.getTime()) {
            timestamp = this.baseTime;
        }

        // Ensure strictly increasing timestamps - if the calculated timestamp is not later than current, advance it
        if (timestamp.getTime() <= this.currentTime.getTime()) {
            const originalTime = timestamp.toISOString();
            timestamp = new Date(this.currentTime.getTime() + 1000); // Add 1 second
            console.log(`⏰ Adjusted timestamp from ${originalTime} to ${timestamp.toISOString()} for strict ordering`);
        }

        // Update current time to this timestamp + 1 second to ensure next event is later
        this.currentTime = new Date(timestamp.getTime() + 1000);

        const event = {
            event_type: eventType,
            user_id: userId,
            device_id: deviceId,
            time: timestamp.getTime(),
            event_properties: {
                ...properties,
                time_range_start: this.baseTime.toISOString(),
                time_range_end: this.endTime.toISOString()
            },
            user_properties: {
                test_scenario: true,
                generated_at: new Date().toISOString()
            }
        };

        this.events.push(event);
        return event;
    }

    // Scenario 1: First-time user-device combinations
    generateFirstTimeCombinations() {
        console.log('=== SCENARIO 1: First-time user-device combinations ===');
        console.log('These should generate identify events when imported\n');

        for (let i = 0; i < 5; i++) {
            const user = SCENARIO_USERS.FIRST_TIME[i];
            const device = SCENARIO_DEVICES.FIRST_TIME[i];
            const eventType = randomChoice(EVENT_TYPES);

            const event = this.addEvent(eventType, user, device, {
                scenario: 'first_time_combination',
                pair_id: `first_time_pair_${i + 1}`,
                expected_identify: true
            });

            log('FIRST-TIME', `New user-device combination #${i + 1}`, event);
        }
    }

    // Scenario 2: Duplicate user-device combinations
    generateDuplicateCombinations() {
        console.log('=== SCENARIO 2: Duplicate user-device combinations ===');
        console.log('These should NOT generate additional identify events\n');

        // Use dedicated duplicate scenario users/devices
        for (let i = 0; i < 3; i++) {
            const user = SCENARIO_USERS.DUPLICATE[i];
            const device = SCENARIO_DEVICES.DUPLICATE[i];

            // Generate multiple events with the same user-device pair
            for (let j = 0; j < 3; j++) {
                const eventType = randomChoice(EVENT_TYPES);
                const event = this.addEvent(eventType, user, device, {
                    scenario: 'duplicate_combination',
                    pair_id: `duplicate_pair_${i + 1}`,
                    duplicate_number: j + 1,
                    expected_identify: j === 0 // Only first occurrence should generate identify
                }, j * 5);

                log('DUPLICATE', `${j === 0 ? 'FIRST' : 'REPEAT'} event ${j + 1} for duplicate pair #${i + 1}`, event);
            }
        }
    }

    // Scenario 3: Multi-device users
    generateMultiDeviceUsers() {
        console.log('=== SCENARIO 3: Multi-device users ===');
        console.log('Same user across multiple devices (each device should get identify event)\n');

        const user = SCENARIO_USERS.MULTI_DEVICE;

        for (let i = 0; i < 4; i++) {
            const device = SCENARIO_DEVICES.MULTI_DEVICE[i];
            const eventType = randomChoice(EVENT_TYPES);
            const deviceType = device.split('_')[2]; // Extract device type from name

            const event = this.addEvent(eventType, user, device, {
                scenario: 'multi_device_user',
                device_type: deviceType,
                device_number: i + 1,
                user_constant: user,
                expected_identify: true // Each new device should generate identify
            }, i * 10);

            log('MULTI-DEVICE', `${user} on ${deviceType} (device ${i + 1}/4)`, event);
        }
    }

    // Scenario 4: Multi-user devices
    generateMultiUserDevices() {
        console.log('=== SCENARIO 4: Multi-user devices ===');
        console.log('Multiple users on same device (each user should get identify event)\n');

        const device = SCENARIO_DEVICES.MULTI_USER;

        for (let i = 0; i < 4; i++) {
            const user = SCENARIO_USERS.MULTI_USER[i];
            const eventType = randomChoice(EVENT_TYPES);
            const userRole = user.split('_')[2] + '_' + user.split('_')[3]; // e.g., "parent_mom"

            const event = this.addEvent(eventType, user, device, {
                scenario: 'multi_user_device',
                user_role: userRole,
                user_number: i + 1,
                device_constant: device,
                expected_identify: true // Each new user should generate identify
            }, i * 8);

            log('MULTI-USER', `${userRole} (user ${i + 1}/4) on ${device}`, event);
        }
    }

    // Scenario 5: Edge cases with special characters and validation
    generateEdgeCases() {
        console.log('=== SCENARIO 5: Edge cases and validation ===');
        console.log('Special characters, unicode, long IDs, etc.\n');

        const edgeCases = [
            // Unicode characters
            { user: SCENARIO_USERS.EDGE_CASE[0], device: SCENARIO_DEVICES.EDGE_CASE[0], name: 'Unicode user and device' },

            // Special characters
            { user: SCENARIO_USERS.EDGE_CASE[1], device: SCENARIO_DEVICES.EDGE_CASE[1], name: 'Email user and colon device' },
            { user: SCENARIO_USERS.EDGE_CASE[2], device: SCENARIO_DEVICES.EDGE_CASE[2], name: 'Hash user and dot device' },

            // Very long IDs
            { user: SCENARIO_USERS.EDGE_CASE[3], device: SCENARIO_DEVICES.EDGE_CASE[4], name: 'Very long user ID' },
            { user: SCENARIO_USERS.EDGE_CASE[4], device: SCENARIO_DEVICES.EDGE_CASE[3], name: 'Very long device ID' },

            // IDs with leading/trailing whitespace (should be trimmed)
            { user: '  ' + SCENARIO_USERS.EDGE_CASE[5] + '  ', device: '  ' + SCENARIO_DEVICES.EDGE_CASE[5] + '  ', name: 'Whitespace-padded IDs' },

            // Numeric-only IDs
            { user: SCENARIO_USERS.EDGE_CASE[6], device: SCENARIO_DEVICES.EDGE_CASE[6], name: 'Numeric IDs' },

            // IDs with mixed case
            { user: SCENARIO_USERS.EDGE_CASE[7], device: SCENARIO_DEVICES.EDGE_CASE[7], name: 'Mixed case IDs' }
        ];

        edgeCases.forEach((testCase, i) => {
            const eventType = randomChoice(EVENT_TYPES);
            const event = this.addEvent(eventType, testCase.user, testCase.device, {
                scenario: 'edge_case',
                test_case: testCase.name,
                case_number: i + 1,
                expected_identify: true // All valid edge cases should generate identify
            }, i * 2);

            log('EDGE-CASE', `${testCase.name} (case ${i + 1}/8)`, event);
        });
    }

    // Scenario 6: Anonymous to identified transitions
    generateAnonymousToIdentified() {
        console.log('=== SCENARIO 6: Anonymous to identified transitions ===');
        console.log('Device-only events followed by user+device events\n');

        for (let i = 0; i < 3; i++) {
            const device = SCENARIO_DEVICES.ANONYMOUS[i];
            const user = SCENARIO_USERS.ANONYMOUS[i];

            // First, anonymous events (device_id only, no user_id)
            for (let j = 0; j < 2; j++) {
                const event = this.addEvent(randomChoice(EVENT_TYPES), null, device, {
                    scenario: 'anonymous_phase',
                    device_constant: device,
                    event_sequence: j + 1,
                    expected_identify: false // Anonymous events don't generate identify
                }, i * 15 + j * 2);

                log('ANONYMOUS', `Anonymous event ${j + 1} on ${device}`, event);
            }

            // Then, user identifies themselves (should generate identify event)
            const event = this.addEvent('user_login', user, device, {
                scenario: 'identification_moment',
                device_constant: device,
                transition: 'anonymous_to_identified',
                expected_identify: true // This should generate identify event
            }, i * 15 + 5);

            log('IDENTIFIED', `${user} identifies on ${device}`, event);

            // Follow up with more identified events (should NOT generate more identify events)
            const followUpEvent = this.addEvent(randomChoice(EVENT_TYPES), user, device, {
                scenario: 'post_identification',
                device_constant: device,
                expected_identify: false // Already identified, no more identify events
            }, i * 15 + 7);

            log('POST-ID', `${user} continues on ${device} (no more identify)`, followUpEvent);
        }
    }

    // Scenario 7: Cross-session user journeys
    generateCrossSessionJourneys() {
        console.log('=== SCENARIO 7: Cross-session user journeys ===');
        console.log('Users switching between devices over time\n');

        const user = SCENARIO_USERS.JOURNEY;
        const journey = [
            { device: SCENARIO_DEVICES.JOURNEY[0], time: 0, context: 'Morning commute', isNewDevice: true },
            { device: SCENARIO_DEVICES.JOURNEY[1], time: 120, context: 'At work', isNewDevice: true },
            { device: SCENARIO_DEVICES.JOURNEY[2], time: 240, context: 'Lunch break', isNewDevice: false }, // Same as phone_commute
            { device: SCENARIO_DEVICES.JOURNEY[3], time: 300, context: 'Back to work', isNewDevice: false }, // Same as laptop_office
            { device: SCENARIO_DEVICES.JOURNEY[4], time: 600, context: 'Evening at home', isNewDevice: true },
            { device: SCENARIO_DEVICES.JOURNEY[5], time: 720, context: 'Before sleep', isNewDevice: false } // Same as phone devices
        ];

        journey.forEach((step, i) => {
            const eventType = randomChoice(EVENT_TYPES);
            const deviceType = step.device.split('_')[1]; // Extract device type
            const event = this.addEvent(eventType, user, step.device, {
                scenario: 'cross_session_journey',
                user_constant: user,
                journey_step: i + 1,
                context: step.context,
                device_type: deviceType,
                expected_identify: step.isNewDevice // Only new devices should generate identify
            }, step.time);

            log('JOURNEY', `${user} step ${i + 1}: ${step.context} on ${deviceType}`, event);
        });
    }

    // Generate all scenarios
    async generateAllScenarios() {
        console.log('🚀 Starting Amplitude Test Data Generation\n');
        console.log(`Using API Key: ${AMPLITUDE_API_KEY}`);
        console.log(`Using Cluster: ${AMPLITUDE_CLUSTER.toUpperCase()}\n`);
        console.log('This will generate comprehensive test data for identify event logic.\n');
        console.log('=' .repeat(70) + '\n');

        this.generateFirstTimeCombinations();
        this.generateDuplicateCombinations();
        this.generateMultiDeviceUsers();
        this.generateMultiUserDevices();
        this.generateEdgeCases();
        this.generateAnonymousToIdentified();
        this.generateCrossSessionJourneys();

        console.log('=' .repeat(70));
        console.log(`✅ Generated ${this.events.length} total events across 7 scenarios\n`);

        // Verify strict timestamp ordering
        this.verifyStrictOrdering();

        return this.events;
    }

    // Verify that all timestamps are strictly increasing
    verifyStrictOrdering() {
        console.log('🔍 Verifying strict timestamp ordering...');

        let violations = 0;
        let previousTime = 0;

        for (let i = 0; i < this.events.length; i++) {
            const event = this.events[i];
            const currentTime = event.time;

            if (currentTime <= previousTime) {
                violations++;
                const prevDate = new Date(previousTime).toISOString();
                const currDate = new Date(currentTime).toISOString();
                console.log(`❌ Timestamp violation at event ${i}: ${currDate} <= ${prevDate}`);
            }

            previousTime = currentTime;
        }

        if (violations === 0) {
            console.log(`✅ All ${this.events.length} events have strictly increasing timestamps`);
            console.log(`📈 Time range: ${new Date(this.events[0].time).toISOString()} → ${new Date(this.events[this.events.length - 1].time).toISOString()}\n`);
        } else {
            console.log(`❌ Found ${violations} timestamp violations\n`);
        }
    }

    // Send events to Amplitude
    async sendToAmplitude() {
        console.log('📤 Sending events to Amplitude...\n');

        let successCount = 0;
        let errorCount = 0;

        // Send events in batches to avoid rate limiting
        const batchSize = 10;
        for (let i = 0; i < this.events.length; i += batchSize) {
            const batch = this.events.slice(i, i + batchSize);

            try {
                const promises = batch.map(event => {
                    // Use Amplitude analytics-node API
                    return amplitude.track(event.event_type, event.event_properties, {
                        user_id: event.user_id,
                        device_id: event.device_id,
                        time: event.time,
                        user_properties: event.user_properties
                    });
                });

                await Promise.all(promises);
                successCount += batch.length;
                console.log(`✅ Batch ${Math.floor(i / batchSize) + 1}: Sent ${batch.length} events`);

                // Small delay between batches
                await new Promise(resolve => setTimeout(resolve, 100));

            } catch (error) {
                errorCount += batch.length;
                console.error(`❌ Batch ${Math.floor(i / batchSize) + 1}: Failed to send events:`, error.message);
            }
        }

        // Flush any remaining events
        try {
            console.log('🔄 Flushing remaining events...');
            await amplitude.flush();
            console.log('✅ Flush completed');
        } catch (error) {
            console.error('❌ Error during flush:', error.message);
        }

        console.log(`\n📊 Summary:`);
        console.log(`   ✅ Successfully sent: ${successCount} events`);
        console.log(`   ❌ Failed to send: ${errorCount} events`);
        console.log(`   📝 Total generated: ${this.events.length} events\n`);

        return { successCount, errorCount, totalCount: this.events.length };
    }

    // Export events to JSON file for manual inspection
    exportToFile(filename = 'amplitude-test-data.json') {
        const fs = require('fs');

        const exportData = {
            metadata: {
                generated_at: new Date().toISOString(),
                total_events: this.events.length,
                api_key: AMPLITUDE_API_KEY,
                scenarios: [
                    'first_time_combinations',
                    'duplicate_combinations',
                    'multi_device_users',
                    'multi_user_devices',
                    'edge_cases',
                    'anonymous_to_identified',
                    'cross_session_journeys'
                ]
            },
            events: this.events
        };

        fs.writeFileSync(filename, JSON.stringify(exportData, null, 2));
        console.log(`💾 Exported ${this.events.length} events to ${filename}\n`);
    }
}

// Main execution
async function main() {
    // Parse time range from environment variables
    let startTime = null;
    let endTime = null;

    try {
        if (AMPLITUDE_START_TIME) {
            startTime = parseTimestamp(AMPLITUDE_START_TIME);
        }
        if (AMPLITUDE_END_TIME) {
            endTime = parseTimestamp(AMPLITUDE_END_TIME);
        }
    } catch (error) {
        console.error(`❌ Error parsing timestamps: ${error.message}`);
        showHelp();
        process.exit(1);
    }

    const generator = new AmplitudeTestGenerator(startTime, endTime);

    try {
        // Generate all test scenarios
        await generator.generateAllScenarios();

        // Export to file for inspection
        generator.exportToFile();

        // Send to Amplitude (comment out if you don't want to send real data)
        if (AMPLITUDE_API_KEY !== 'test_amplitude_key') {
            await generator.sendToAmplitude();

            // Final flush to ensure all events are sent
            try {
                console.log('🔄 Final flush to ensure all events are sent...');
                await amplitude.flush();
                console.log('✅ Final flush completed');
            } catch (error) {
                console.error('❌ Error during final flush:', error.message);
            }
        } else {
            console.log('⚠️  Using test API key - skipping actual Amplitude sending');
            console.log('   Set AMPLITUDE_API_KEY environment variable to send real data');
            console.log('   Set AMPLITUDE_CLUSTER=eu for EU cluster (defaults to us)\n');
        }

        console.log('🎉 Test data generation complete!\n');
        console.log('📊 Expected Identify Events Summary:');
        console.log('   ✅ Scenario 1 (First-time): 5 identify events');
        console.log('   ✅ Scenario 2 (Duplicates): 3 identify events (only first occurrence)');
        console.log('   ✅ Scenario 3 (Multi-device): 4 identify events');
        console.log('   ✅ Scenario 4 (Multi-user): 4 identify events');
        console.log('   ✅ Scenario 5 (Edge cases): 8 identify events');
        console.log('   ✅ Scenario 6 (Anonymous→ID): 3 identify events');
        console.log('   ✅ Scenario 7 (Journey): 3 identify events (new devices only)');
        console.log('   📈 TOTAL EXPECTED: 30 identify events\n');
        console.log('Next steps:');
        console.log('1. Review the generated data in amplitude-test-data.json');
        console.log('2. Export this data from Amplitude using their export API');
        console.log('3. Run PostHog batch import with generate_identify_events=true');
        console.log('4. Verify exactly 30 identify events are created');
        console.log('5. Check user-device combinations match expected scenarios\n');

    } catch (error) {
        console.error('❌ Error during test data generation:', error);
        process.exit(1);
    }
}

// Run if called directly
if (require.main === module) {
    main();
}

module.exports = { AmplitudeTestGenerator };
