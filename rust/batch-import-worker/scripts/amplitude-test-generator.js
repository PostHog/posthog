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

Usage: node amplitude-test-generator.js [--groups-only]

Options:
  --groups-only               Generate only group scenarios (scenarios 8-15), skip identify scenarios

Environment Variables:
  AMPLITUDE_API_KEY           Your Amplitude API key (required for sending)
  AMPLITUDE_CLUSTER           Cluster: 'us' (default) or 'eu'
  AMPLITUDE_START_TIME        Start timestamp for events (ISO format or relative)
                              Examples: '2024-01-01T00:00:00Z', '2024-01-01', '1 week ago'
  AMPLITUDE_END_TIME          End timestamp for events (ISO format or relative)
                              Examples: '2024-01-07T23:59:59Z', '2024-01-07', 'now'

Examples:
  # Generate all scenarios (identify + groups)
  node amplitude-test-generator.js

  # Generate only group scenarios
  node amplitude-test-generator.js --groups-only

  # Generate events for a specific week
  AMPLITUDE_START_TIME='2024-01-01T00:00:00Z' AMPLITUDE_END_TIME='2024-01-07T23:59:59Z' node amplitude-test-generator.js

  # Generate only group events for testing
  AMPLITUDE_START_TIME='1 week ago' AMPLITUDE_END_TIME='now' node amplitude-test-generator.js --groups-only
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

// Group-specific test data
const SCENARIO_GROUPS = {
    SINGLE_GROUP: {
        'company': [
            'acme-corp',
            'tech-startup-xyz',
            'enterprise-solutions-inc',
            'global-ventures-ltd'
        ]
    },
    MULTIPLE_GROUPS: {
        'company': ['acme-corp', 'tech-startup-xyz'],
        'team': ['engineering', 'product', 'marketing', 'sales'],
        'department': ['backend', 'frontend', 'mobile', 'data']
    },
    EDGE_CASE_GROUPS: {
        'company': ['unicode-公司', 'special-chars@#$', 'very-long-' + 'x'.repeat(30)],
        'team': ['spaced team name', 'UPPERCASE_TEAM', 'kebab-case-team']
    }
};

const SCENARIO_GROUP_PROPERTIES = {
    RICH_PROPERTIES: {
        company_name: 'Acme Corporation',
        industry: 'Technology',
        size: 250,
        founded: 2010,
        location: 'San Francisco, CA',
        plan: 'enterprise',
        mrr: 50000,
        is_public: false
    },
    MINIMAL_PROPERTIES: {
        name: 'Tech Startup XYZ',
        size: 15
    },
    TEAM_PROPERTIES: {
        team_name: 'Engineering Team',
        team_lead: 'Sarah Johnson',
        team_size: 12,
        budget: 500000,
        tech_stack: ['React', 'Node.js', 'PostgreSQL']
    },
    DEPARTMENT_PROPERTIES: {
        department_name: 'Backend Engineering',
        head_count: 8,
        primary_language: 'Rust',
        deployment_frequency: 'daily'
    }
};

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

    async addEvent(eventType, userId, deviceId, properties = {}, offsetMinutes = 0, groups = null, groupProperties = null) {
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

        // Add groups if provided (Amplitude format)
        if (groups) {
            event.groups = groups;
        }

        // Add group_properties if provided (Amplitude format)
        if (groupProperties) {
            event.group_properties = groupProperties;
        }

        this.events.push(event);

        // Send to Amplitude immediately if API key is configured
        if (AMPLITUDE_API_KEY !== 'test_amplitude_key') {
            try {
                await amplitude.track(event.event_type, event.event_properties, {
                    user_id: event.user_id,
                    device_id: event.device_id,
                    time: event.time,
                    user_properties: event.user_properties,
                    groups: event.groups
                });
                await amplitude.flush();
                console.log(`📤 Sent and flushed regular event: ${event.event_type}`);
            } catch (error) {
                console.error(`❌ Failed to send regular event: ${error.message}`);
            }
        }

        return event;
    }

    async addGroupIdentifyEvent(groupType, groupKey, properties = {}, offsetMinutes = 0) {
        let timestamp = generateTimestamp(this.currentTime, offsetMinutes);

        // Ensure timestamp stays within bounds
        if (timestamp.getTime() > this.endTime.getTime()) {
            timestamp = this.endTime;
        }
        if (timestamp.getTime() < this.baseTime.getTime()) {
            timestamp = this.baseTime;
        }

        // Ensure strictly increasing timestamps
        if (timestamp.getTime() <= this.currentTime.getTime()) {
            const originalTime = timestamp.toISOString();
            timestamp = new Date(this.currentTime.getTime() + 1000); // Add 1 second
            console.log(`⏰ Adjusted timestamp from ${originalTime} to ${timestamp.toISOString()} for strict ordering`);
        }

        // Update current time to this timestamp + 1 second
        this.currentTime = new Date(timestamp.getTime() + 1000);

        const event = {
            event_type: '$groupidentify',
            group_type: groupType,
            group_key: groupKey,
            time: timestamp.getTime(),
            group_properties: properties
        };

        this.events.push(event);

        // Send to Amplitude immediately if API key is configured
        if (AMPLITUDE_API_KEY !== 'test_amplitude_key') {
            try {
                const groupIdentify = new amplitude.Identify();

                // Add all group properties
                for (const [key, value] of Object.entries(properties)) {
                    groupIdentify.set(key, value);
                }

                await amplitude.groupIdentify(groupType, groupKey, groupIdentify);
                await amplitude.flush();
                console.log(`📤 Sent and flushed group identify: ${groupType}:${groupKey}`);
            } catch (error) {
                console.error(`❌ Failed to send group identify event: ${error.message}`);
            }
        }

        return event;
    }

    // Scenario 1: First-time user-device combinations
    async generateFirstTimeCombinations() {
        console.log('=== SCENARIO 1: First-time user-device combinations ===');
        console.log('These should generate identify events when imported\n');

        for (let i = 0; i < 5; i++) {
            const user = SCENARIO_USERS.FIRST_TIME[i];
            const device = SCENARIO_DEVICES.FIRST_TIME[i];
            const eventType = randomChoice(EVENT_TYPES);

            const event = await this.addEvent(eventType, user, device, {
                scenario: 'first_time_combination',
                pair_id: `first_time_pair_${i + 1}`,
                expected_identify: true
            });

            log('FIRST-TIME', `New user-device combination #${i + 1}`, event);
        }
    }

    // Scenario 2: Duplicate user-device combinations
    async generateDuplicateCombinations() {
        console.log('=== SCENARIO 2: Duplicate user-device combinations ===');
        console.log('These should NOT generate additional identify events\n');

        // Use dedicated duplicate scenario users/devices
        for (let i = 0; i < 3; i++) {
            const user = SCENARIO_USERS.DUPLICATE[i];
            const device = SCENARIO_DEVICES.DUPLICATE[i];

            // Generate multiple events with the same user-device pair
            for (let j = 0; j < 3; j++) {
                const eventType = randomChoice(EVENT_TYPES);
                const event = await this.addEvent(eventType, user, device, {
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
    async generateMultiDeviceUsers() {
        console.log('=== SCENARIO 3: Multi-device users ===');
        console.log('Same user across multiple devices (each device should get identify event)\n');

        const user = SCENARIO_USERS.MULTI_DEVICE;

        for (let i = 0; i < 4; i++) {
            const device = SCENARIO_DEVICES.MULTI_DEVICE[i];
            const eventType = randomChoice(EVENT_TYPES);
            const deviceType = device.split('_')[2]; // Extract device type from name

            const event = await this.addEvent(eventType, user, device, {
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
    async generateMultiUserDevices() {
        console.log('=== SCENARIO 4: Multi-user devices ===');
        console.log('Multiple users on same device (each user should get identify event)\n');

        const device = SCENARIO_DEVICES.MULTI_USER;

        for (let i = 0; i < 4; i++) {
            const user = SCENARIO_USERS.MULTI_USER[i];
            const eventType = randomChoice(EVENT_TYPES);
            const userRole = user.split('_')[2] + '_' + user.split('_')[3]; // e.g., "parent_mom"

            const event = await this.addEvent(eventType, user, device, {
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
    async generateEdgeCases() {
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

        for (let i = 0; i < edgeCases.length; i++) {
            const testCase = edgeCases[i];
            const eventType = randomChoice(EVENT_TYPES);
            const event = await this.addEvent(eventType, testCase.user, testCase.device, {
                scenario: 'edge_case',
                test_case: testCase.name,
                case_number: i + 1,
                expected_identify: true // All valid edge cases should generate identify
            }, i * 2);

            log('EDGE-CASE', `${testCase.name} (case ${i + 1}/8)`, event);
        }
    }

    // Scenario 6: Anonymous to identified transitions
    async generateAnonymousToIdentified() {
        console.log('=== SCENARIO 6: Anonymous to identified transitions ===');
        console.log('Device-only events followed by user+device events\n');

        for (let i = 0; i < 3; i++) {
            const device = SCENARIO_DEVICES.ANONYMOUS[i];
            const user = SCENARIO_USERS.ANONYMOUS[i];

            // First, anonymous events (device_id only, no user_id)
            for (let j = 0; j < 2; j++) {
                const event = await this.addEvent(randomChoice(EVENT_TYPES), null, device, {
                    scenario: 'anonymous_phase',
                    device_constant: device,
                    event_sequence: j + 1,
                    expected_identify: false // Anonymous events don't generate identify
                }, i * 15 + j * 2);

                log('ANONYMOUS', `Anonymous event ${j + 1} on ${device}`, event);
            }

            // Then, user identifies themselves (should generate identify event)
            const event = await this.addEvent('user_login', user, device, {
                scenario: 'identification_moment',
                device_constant: device,
                transition: 'anonymous_to_identified',
                expected_identify: true // This should generate identify event
            }, i * 15 + 5);

            log('IDENTIFIED', `${user} identifies on ${device}`, event);

            // Follow up with more identified events (should NOT generate more identify events)
            const followUpEvent = await this.addEvent(randomChoice(EVENT_TYPES), user, device, {
                scenario: 'post_identification',
                device_constant: device,
                expected_identify: false // Already identified, no more identify events
            }, i * 15 + 7);

            log('POST-ID', `${user} continues on ${device} (no more identify)`, followUpEvent);
        }
    }

    // Scenario 7: Cross-session user journeys
    async generateCrossSessionJourneys() {
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

        for (let i = 0; i < journey.length; i++) {
            const step = journey[i];
            const eventType = randomChoice(EVENT_TYPES);
            const deviceType = step.device.split('_')[1]; // Extract device type
            const event = await this.addEvent(eventType, user, step.device, {
                scenario: 'cross_session_journey',
                user_constant: user,
                journey_step: i + 1,
                context: step.context,
                device_type: deviceType,
                expected_identify: step.isNewDevice // Only new devices should generate identify
            }, step.time);

            log('JOURNEY', `${user} step ${i + 1}: ${step.context} on ${deviceType}`, event);
        }
    }

    // Scenario 8: Single group events
    async generateSingleGroupEvents() {
        console.log('=== SCENARIO 8: Single group events ===');
        console.log('Events with a single group (company only)\n');

        const companies = SCENARIO_GROUPS.SINGLE_GROUP.company;

        for (let i = 0; i < companies.length; i++) {
            const user = `single_group_user_${i + 1}`;
            const device = `single_group_device_${i + 1}`;
            const company = companies[i];
            const eventType = randomChoice(EVENT_TYPES);

            // Use rich properties for first two, minimal for others
            const groupProperties = i < 2 ?
                { ...SCENARIO_GROUP_PROPERTIES.RICH_PROPERTIES, company_id: company } :
                { ...SCENARIO_GROUP_PROPERTIES.MINIMAL_PROPERTIES, company_id: company };

            // Add the group identify event first
            const groupIdentifyEvent = await this.addGroupIdentifyEvent('company', company, groupProperties, i * 5);
            log('GROUP-IDENTIFY', `Company "${company}" identified`, groupIdentifyEvent);

            // Then add regular event with group association (no group_properties)
            const event = await this.addEvent(eventType, user, device, {
                scenario: 'single_group',
                company_id: company,
                event_sequence: 1,
                expected_group_identify: true
            }, i * 5 + 1, { company }); // Note: no groupProperties parameter

            log('SINGLE-GROUP', `${user} in company "${company}"`, event);
        }
    }

    // Scenario 9: Multiple groups events
    async generateMultipleGroupsEvents() {
        console.log('=== SCENARIO 9: Multiple groups events ===');
        console.log('Events with multiple groups (company + team + department)\n');

        const companies = SCENARIO_GROUPS.MULTIPLE_GROUPS.company;
        const teams = SCENARIO_GROUPS.MULTIPLE_GROUPS.team;
        const departments = SCENARIO_GROUPS.MULTIPLE_GROUPS.department;

        for (let i = 0; i < 4; i++) {
            const user = `multi_group_user_${i + 1}`;
            const device = `multi_group_device_${i + 1}`;
            const company = companies[i % companies.length];
            const team = teams[i % teams.length];
            const department = departments[i % departments.length];
            const eventType = randomChoice(EVENT_TYPES);

            // Add group identify events first
            const companyGroupIdentify = await this.addGroupIdentifyEvent('company', company, {
                ...SCENARIO_GROUP_PROPERTIES.RICH_PROPERTIES,
                company_id: company
            }, i * 8);

            const teamGroupIdentify = await this.addGroupIdentifyEvent('team', team, {
                ...SCENARIO_GROUP_PROPERTIES.TEAM_PROPERTIES,
                team_id: team
            }, i * 8 + 1);

            const departmentGroupIdentify = await this.addGroupIdentifyEvent('department', department, {
                ...SCENARIO_GROUP_PROPERTIES.DEPARTMENT_PROPERTIES,
                department_id: department
            }, i * 8 + 2);

            log('GROUP-IDENTIFY', `Company "${company}" identified`, companyGroupIdentify);
            log('GROUP-IDENTIFY', `Team "${team}" identified`, teamGroupIdentify);
            log('GROUP-IDENTIFY', `Department "${department}" identified`, departmentGroupIdentify);

            // Then add regular event with group associations
            const event = await this.addEvent(eventType, user, device, {
                scenario: 'multiple_groups',
                company_id: company,
                team_id: team,
                department_id: department,
                expected_group_identify: 3 // Should generate 3 group identify events
            }, i * 8 + 3, { company, team, department });

            log('MULTI-GROUP', `${user} in company "${company}", team "${team}", department "${department}"`, event);
        }
    }

    // Scenario 10: Groups without group_properties
    async generateGroupsWithoutProperties() {
        console.log('=== SCENARIO 10: Groups without group_properties ===');
        console.log('Events with groups but no group_properties field\n');

        for (let i = 0; i < 3; i++) {
            const user = `no_props_user_${i + 1}`;
            const device = `no_props_device_${i + 1}`;
            const company = `no-props-company-${i + 1}`;
            const eventType = randomChoice(EVENT_TYPES);

            // Add group identify event with empty properties
            const groupIdentifyEvent = await this.addGroupIdentifyEvent('company', company, {}, i * 4);
            log('GROUP-IDENTIFY', `Company "${company}" identified (empty properties)`, groupIdentifyEvent);

            // Then add regular event with group association
            const event = await this.addEvent(eventType, user, device, {
                scenario: 'groups_without_properties',
                company_id: company,
                expected_group_identify: true,
                expected_group_properties: 'empty' // Should use empty properties
            }, i * 4 + 1, { company });

            log('NO-PROPS', `${user} in company "${company}" (no group properties)`, event);
        }
    }

    // Scenario 11: Mixed events (some with groups, some without)
    async generateMixedGroupEvents() {
        console.log('=== SCENARIO 11: Mixed events (some with groups, some without) ===');
        console.log('Alternating between events with and without groups\n');

        const baseUser = 'mixed_events_user';
        const baseDevice = 'mixed_events_device';

        for (let i = 0; i < 6; i++) {
            const eventType = randomChoice(EVENT_TYPES);
            const hasGroups = i % 2 === 0; // Alternate: even indices have groups

            if (hasGroups) {
                const company = `mixed-company-${Math.floor(i / 2) + 1}`;

                // Add group identify event first
                const groupIdentifyEvent = await this.addGroupIdentifyEvent('company', company,
                    SCENARIO_GROUP_PROPERTIES.MINIMAL_PROPERTIES, i * 3);
                log('GROUP-IDENTIFY', `Company "${company}" identified`, groupIdentifyEvent);

                // Then add regular event with group association
                const event = await this.addEvent(eventType, baseUser, baseDevice, {
                    scenario: 'mixed_events_with_groups',
                    sequence: i + 1,
                    has_groups: true,
                    expected_group_identify: true
                }, i * 3 + 1, { company });

                log('MIXED-WITH', `Event ${i + 1}: ${eventType} with groups (company: ${company})`, event);
            } else {
                const event = await this.addEvent(eventType, baseUser, baseDevice, {
                    scenario: 'mixed_events_without_groups',
                    sequence: i + 1,
                    has_groups: false,
                    expected_group_identify: false
                }, i * 3);

                log('MIXED-WITHOUT', `Event ${i + 1}: ${eventType} without groups`, event);
            }
        }
    }

    // Scenario 12: Edge cases with special characters in group names
    async generateGroupEdgeCases() {
        console.log('=== SCENARIO 12: Group edge cases ===');
        console.log('Groups with special characters, unicode, long names, etc.\n');

        const edgeCases = [
            { company: SCENARIO_GROUPS.EDGE_CASE_GROUPS.company[0], team: SCENARIO_GROUPS.EDGE_CASE_GROUPS.team[0], name: 'Unicode group names' },
            { company: SCENARIO_GROUPS.EDGE_CASE_GROUPS.company[1], team: SCENARIO_GROUPS.EDGE_CASE_GROUPS.team[1], name: 'Special characters in groups' },
            { company: SCENARIO_GROUPS.EDGE_CASE_GROUPS.company[2], team: SCENARIO_GROUPS.EDGE_CASE_GROUPS.team[2], name: 'Very long group names' }
        ];

        for (let i = 0; i < edgeCases.length; i++) {
            const testCase = edgeCases[i];
            const user = `edge_group_user_${i + 1}`;
            const device = `edge_group_device_${i + 1}`;
            const eventType = randomChoice(EVENT_TYPES);

            // Add group identify events first
            const companyGroupIdentify = await this.addGroupIdentifyEvent('company', testCase.company, {
                ...SCENARIO_GROUP_PROPERTIES.MINIMAL_PROPERTIES,
                edge_case_test: true,
                company_name: testCase.company
            }, i * 5);

            const teamGroupIdentify = await this.addGroupIdentifyEvent('team', testCase.team, {
                ...SCENARIO_GROUP_PROPERTIES.TEAM_PROPERTIES,
                edge_case_test: true,
                team_name: testCase.team
            }, i * 5 + 1);

            log('GROUP-IDENTIFY', `Company "${testCase.company}" identified (${testCase.name})`, companyGroupIdentify);
            log('GROUP-IDENTIFY', `Team "${testCase.team}" identified (${testCase.name})`, teamGroupIdentify);

            // Then add regular event with group associations
            const event = await this.addEvent(eventType, user, device, {
                scenario: 'group_edge_cases',
                test_case: testCase.name,
                case_number: i + 1,
                expected_group_identify: 2 // company + team
            }, i * 5 + 2, { company: testCase.company, team: testCase.team });

            log('GROUP-EDGE', `${testCase.name} (case ${i + 1}/3)`, event);
        }
    }

    // Scenario 13: User events with groups imported BEFORE group identify
    async generateUserEventsBeforeGroupIdentify() {
        console.log('=== SCENARIO 13: User events with groups BEFORE group identify ===');
        console.log('Common real-world scenario: user events reference groups before group identify events\n');

        const company = 'early-reference-company';
        const team = 'early-reference-team';
        const user = 'early_reference_user';
        const device = 'early_reference_device';

        // Step 1: User events that reference groups but group identify events haven't been sent yet
        // This simulates the common case where user events reference groups before
        // the groups are "officially" defined via group identify events
        for (let i = 0; i < 3; i++) {
            const eventType = randomChoice(EVENT_TYPES);
            const event = await this.addEvent(eventType, user, device, {
                scenario: 'user_events_before_group_identify',
                sequence: i + 1,
                phase: 'user_events_first',
                expected_group_identify: false, // No group identify yet
                note: 'Groups referenced but not yet identified'
            }, i * 2, { company, team }); // Groups but no group_properties

            log('BEFORE-GROUP', `User event ${i + 1}: ${eventType} referencing groups (no group identify yet)`, event);
        }

        // Step 2: Later, group identify events with full properties
        // This simulates when group properties are finally provided
        const companyGroupIdentify = await this.addGroupIdentifyEvent('company', company, {
            ...SCENARIO_GROUP_PROPERTIES.RICH_PROPERTIES,
            company_id: company,
            setup_phase: 'delayed_group_identification'
        }, 10);

        const teamGroupIdentify = await this.addGroupIdentifyEvent('team', team, {
            ...SCENARIO_GROUP_PROPERTIES.TEAM_PROPERTIES,
            team_id: team,
            setup_phase: 'delayed_group_identification'
        }, 11);

        log('AFTER-GROUP', `Company "${company}" group identify (after user events)`, companyGroupIdentify);
        log('AFTER-GROUP', `Team "${team}" group identify (after user events)`, teamGroupIdentify);

        // Step 3: More user events after group identification
        for (let i = 0; i < 2; i++) {
            const eventType = randomChoice(EVENT_TYPES);
            const event = await this.addEvent(eventType, user, device, {
                scenario: 'user_events_after_group_identify',
                sequence: i + 1,
                phase: 'user_events_after',
                expected_group_identify: false, // Groups already identified
                note: 'User events after groups are identified'
            }, 12 + i * 2, { company, team });

            log('AFTER-USER', `User event after group identify ${i + 1}: ${eventType}`, event);
        }
    }

    // Scenario 14: Events with groups but NO group identify events
    async generateEventsWithGroupsNoIdentify() {
        console.log('=== SCENARIO 14: Events with groups but NO group identify events ===');
        console.log('Events that reference groups but no group identify events are ever sent\n');

        const scenarios = [
            { user: 'orphan_group_user_1', device: 'orphan_group_device_1', company: 'orphaned-company-1', team: 'orphaned-team-1' },
            { user: 'orphan_group_user_2', device: 'orphan_group_device_2', company: 'orphaned-company-2' },
            { user: 'orphan_group_user_3', device: 'orphan_group_device_3', company: 'never-identified-corp', team: 'mystery-team', department: 'unknown-dept' }
        ];

        for (let i = 0; i < scenarios.length; i++) {
            const scenario = scenarios[i];
            const eventType = randomChoice(EVENT_TYPES);
            const groups = {};

            // Build groups object based on what's available in the scenario
            if (scenario.company) groups.company = scenario.company;
            if (scenario.team) groups.team = scenario.team;
            if (scenario.department) groups.department = scenario.department;

            // Add regular event with group associations (but NO group identify events)
            const event = await this.addEvent(eventType, scenario.user, scenario.device, {
                scenario: 'events_with_groups_no_identify',
                case_number: i + 1,
                expected_group_identify: false, // No group identify events
                note: 'Groups referenced but never identified'
            }, i * 3, groups); // Groups but no corresponding group identify events

            const groupList = Object.entries(groups).map(([type, value]) => `${type}: "${value}"`).join(', ');
            log('ORPHAN-GROUP', `${scenario.user} event with orphaned groups (${groupList})`, event);
        }
    }

    // Scenario 15: Multiple group updates for single user
    async generateMultipleGroupUpdatesForUser() {
        console.log('=== SCENARIO 15: Multiple group updates for single user ===');
        console.log('One user with multiple groups that get updated several times in different ways\n');

        const user = 'multi_update_user';
        const device = 'multi_update_device';

        // Initial group properties
        let companyProperties = {
            company_name: 'StartupCorp',
            industry: 'Technology',
            size: 50,
            plan: 'basic',
            mrr: 10000,
            is_public: false
        };

        let teamProperties = {
            team_name: 'Backend Team',
            team_lead: 'Alice Smith',
            team_size: 5,
            budget: 100000,
            primary_language: 'Python'
        };

        let departmentProperties = {
            department_name: 'Engineering',
            head_count: 15,
            deployment_frequency: 'weekly'
        };

        // Event 1: Initial group identify events for all groups
        const companyGroupIdentify1 = await this.addGroupIdentifyEvent('company', 'startup-corp', companyProperties, 0);
        const teamGroupIdentify1 = await this.addGroupIdentifyEvent('team', 'backend-team', teamProperties, 1);
        const departmentGroupIdentify1 = await this.addGroupIdentifyEvent('department', 'engineering', departmentProperties, 2);

        log('MULTI-UPDATE', 'Initial company group identify', companyGroupIdentify1);
        log('MULTI-UPDATE', 'Initial team group identify', teamGroupIdentify1);
        log('MULTI-UPDATE', 'Initial department group identify', departmentGroupIdentify1);

        // Event 2: User signup event with all groups
        const initialEvent = await this.addEvent('signup', user, device, {
            scenario: 'multiple_group_updates',
            phase: 'initial_signup',
            expected_group_identify: 3 // company + team + department
        }, 3, {
            company: 'startup-corp',
            team: 'backend-team',
            department: 'engineering'
        });

        log('MULTI-UPDATE', 'Initial signup with 3 groups', initialEvent);

        // Event 3: Company gets promoted (plan upgrade, size increase)
        companyProperties = {
            ...companyProperties,
            plan: 'pro',
            size: 75,
            mrr: 25000
        };

        const companyGroupIdentify2 = await this.addGroupIdentifyEvent('company', 'startup-corp', companyProperties, 60);
        log('MULTI-UPDATE', 'Company plan upgraded group identify', companyGroupIdentify2);

        const companyUpdateEvent = await this.addEvent('subscription_upgrade', user, device, {
            scenario: 'multiple_group_updates',
            phase: 'company_upgrade',
            expected_group_identify: 1 // only company changes
        }, 61, {
            company: 'startup-corp',
            team: 'backend-team',
            department: 'engineering'
        });

        log('MULTI-UPDATE', 'Company plan upgraded (should trigger company $groupidentify)', companyUpdateEvent);

        // Event 4: User switches teams
        teamProperties = {
            team_name: 'Frontend Team',
            team_lead: 'Bob Johnson',
            team_size: 8,
            budget: 150000,
            primary_language: 'TypeScript'
        };

        const teamGroupIdentify2 = await this.addGroupIdentifyEvent('team', 'frontend-team', teamProperties, 120);
        log('MULTI-UPDATE', 'User switches to frontend team group identify', teamGroupIdentify2);

        const teamSwitchEvent = await this.addEvent('team_switch', user, device, {
            scenario: 'multiple_group_updates',
            phase: 'team_switch',
            expected_group_identify: 1 // only team changes
        }, 121, {
            company: 'startup-corp',
            team: 'frontend-team', // Changed team
            department: 'engineering'
        });

        log('MULTI-UPDATE', 'User switches to frontend team (should trigger team $groupidentify)', teamSwitchEvent);

        // Event 5: Multiple changes at once (company grows, department restructures)
        companyProperties = {
            ...companyProperties,
            size: 100,
            plan: 'enterprise',
            mrr: 50000,
            is_public: true
        };

        departmentProperties = {
            department_name: 'Product Engineering',
            head_count: 25,
            deployment_frequency: 'daily',
            tech_lead: 'Charlie Brown'
        };

        const companyGroupIdentify3 = await this.addGroupIdentifyEvent('company', 'startup-corp', companyProperties, 180);
        const departmentGroupIdentify2 = await this.addGroupIdentifyEvent('department', 'engineering', departmentProperties, 181);

        log('MULTI-UPDATE', 'Company IPO group identify', companyGroupIdentify3);
        log('MULTI-UPDATE', 'Department restructure group identify', departmentGroupIdentify2);

        const multipleChangesEvent = await this.addEvent('company_milestone', user, device, {
            scenario: 'multiple_group_updates',
            phase: 'multiple_simultaneous_changes',
            expected_group_identify: 2 // company + department change
        }, 182, {
            company: 'startup-corp',
            team: 'frontend-team',
            department: 'engineering'
        });

        log('MULTI-UPDATE', 'Company IPO + department restructure (should trigger 2 $groupidentify events)', multipleChangesEvent);

        // Event 6: User adds a new group type (project)
        const projectProperties = {
            project_name: 'Mobile App Rewrite',
            project_lead: user,
            deadline: '2024-06-01',
            budget: 200000,
            status: 'active'
        };

        const projectGroupIdentify1 = await this.addGroupIdentifyEvent('project', 'mobile-rewrite', projectProperties, 240);
        log('MULTI-UPDATE', 'User assigned to new project group identify', projectGroupIdentify1);

        const newGroupEvent = await this.addEvent('project_assigned', user, device, {
            scenario: 'multiple_group_updates',
            phase: 'new_group_added',
            expected_group_identify: 1 // new project group
        }, 241, {
            company: 'startup-corp',
            team: 'frontend-team',
            department: 'engineering',
            project: 'mobile-rewrite' // New group type
        });

        log('MULTI-UPDATE', 'User assigned to new project (should trigger project $groupidentify)', newGroupEvent);

        // Event 7: Only team properties change (no group membership change)
        teamProperties = {
            ...teamProperties,
            team_size: 10,
            budget: 200000,
            sprint_velocity: 45
        };

        const teamGroupIdentify3 = await this.addGroupIdentifyEvent('team', 'frontend-team', teamProperties, 300);
        log('MULTI-UPDATE', 'Team expands group identify', teamGroupIdentify3);

        const teamUpdateEvent = await this.addEvent('team_expansion', user, device, {
            scenario: 'multiple_group_updates',
            phase: 'team_properties_update',
            expected_group_identify: 1 // team properties changed
        }, 301, {
            company: 'startup-corp',
            team: 'frontend-team',
            department: 'engineering',
            project: 'mobile-rewrite'
        });

        log('MULTI-UPDATE', 'Team expands (should trigger team $groupidentify)', teamUpdateEvent);

        // Event 8: User leaves project but stays in other groups
        const projectLeaveEvent = await this.addEvent('project_completed', user, device, {
            scenario: 'multiple_group_updates',
            phase: 'group_removed',
            expected_group_identify: 0 // no group properties changed, just membership
        }, 360, {
            company: 'startup-corp',
            team: 'frontend-team',
            department: 'engineering'
            // project removed from groups
        });

        log('MULTI-UPDATE', 'User completes project (no $groupidentify, just group membership change)', projectLeaveEvent);

        // Event 9: Final event with no changes (should not trigger any group identifies)
        const noChangeEvent = await this.addEvent('daily_activity', user, device, {
            scenario: 'multiple_group_updates',
            phase: 'no_changes',
            expected_group_identify: 0 // no changes
        }, 420, {
            company: 'startup-corp',
            team: 'frontend-team',
            department: 'engineering'
        });

        log('MULTI-UPDATE', 'Daily activity with no group changes (no $groupidentify expected)', noChangeEvent);
    }

    // Generate all scenarios
    async generateAllScenarios(groupsOnly = false) {
        console.log('🚀 Starting Amplitude Test Data Generation\n');
        console.log(`Using API Key: ${AMPLITUDE_API_KEY}`);
        console.log(`Using Cluster: ${AMPLITUDE_CLUSTER.toUpperCase()}\n`);

        if (groupsOnly) {
            console.log('🏢 Groups-only mode: Generating group scenarios only (8-15)\n');
            console.log('=' .repeat(70) + '\n');

            // Only group scenarios
            await this.generateSingleGroupEvents();
            await this.generateMultipleGroupsEvents();
            await this.generateGroupsWithoutProperties();
            await this.generateMixedGroupEvents();
            await this.generateGroupEdgeCases();
            await this.generateUserEventsBeforeGroupIdentify();
            await this.generateEventsWithGroupsNoIdentify();
            await this.generateMultipleGroupUpdatesForUser();

            console.log('=' .repeat(70));
            console.log(`✅ Generated ${this.events.length} total events across 8 group scenarios\n`);
        } else {
            console.log('This will generate comprehensive test data for identify event logic AND group events.\n');
            console.log('=' .repeat(70) + '\n');

            // Original identify scenarios
            await this.generateFirstTimeCombinations();
            await this.generateDuplicateCombinations();
            await this.generateMultiDeviceUsers();
            await this.generateMultiUserDevices();
            await this.generateEdgeCases();
            await this.generateAnonymousToIdentified();
            await this.generateCrossSessionJourneys();

            // New group scenarios
            await this.generateSingleGroupEvents();
            await this.generateMultipleGroupsEvents();
            await this.generateGroupsWithoutProperties();
            await this.generateMixedGroupEvents();
            await this.generateGroupEdgeCases();
            await this.generateUserEventsBeforeGroupIdentify();
            await this.generateEventsWithGroupsNoIdentify();
            await this.generateMultipleGroupUpdatesForUser();

            console.log('=' .repeat(70));
            console.log(`✅ Generated ${this.events.length} total events across 15 scenarios\n`);
        }

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
                    if (event.event_type === '$groupidentify') {
                        // Send group identify event
                        const groupIdentify = new amplitude.Identify();

                        // Add all group properties
                        for (const [key, value] of Object.entries(event.group_properties || {})) {
                            groupIdentify.set(key, value);
                        }

                        return amplitude.groupIdentify(
                            event.group_type,
                            event.group_key,
                            groupIdentify
                        );
                    } else {
                        // Send regular event with groups (but NO group_properties)
                        return amplitude.track(event.event_type, event.event_properties, {
                            user_id: event.user_id,
                            device_id: event.device_id,
                            time: event.time,
                            user_properties: event.user_properties,
                            groups: event.groups // Include groups in regular events
                        });
                    }
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

        console.log(`\n📊 Regular Events Summary:`);
        console.log(`   ✅ Successfully sent: ${successCount} regular events`);
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
                    // Original identify scenarios
                    'first_time_combinations',
                    'duplicate_combinations',
                    'multi_device_users',
                    'multi_user_devices',
                    'edge_cases',
                    'anonymous_to_identified',
                    'cross_session_journeys',
                    // New group scenarios
                    'single_group_events',
                    'multiple_groups_events',
                    'groups_without_properties',
                    'mixed_group_events',
                    'group_edge_cases',
                    'user_events_before_group_identify',
                    'events_with_groups_no_identify',
                    'multiple_group_updates_for_user'
                ],
                expected_identify_events: 30,
                expected_group_identify_events: 38,
                group_test_cases: [
                    'rich_vs_minimal_group_properties',
                    'multiple_groups_per_event',
                    'groups_without_group_properties_field',
                    'mixed_events_with_and_without_groups',
                    'unicode_and_special_characters_in_groups',
                    'user_events_before_group_identification',
                    'events_with_groups_but_no_group_identify',
                    'multiple_group_property_updates_single_user'
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
    // Parse command-line arguments
    const args = process.argv.slice(2);
    const groupsOnly = args.includes('--groups-only');

    if (args.includes('--help') || args.includes('-h')) {
        showHelp();
        process.exit(0);
    }

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
        // Generate test scenarios (all or groups-only based on flag)
        await generator.generateAllScenarios(groupsOnly);

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

        if (groupsOnly) {
            console.log('🏢 Expected Group Identify Events Summary (Groups-Only Mode):');
            console.log('   ✅ Scenario 8 (Single groups): 4 group identify events');
            console.log('   ✅ Scenario 9 (Multiple groups): 12 group identify events (4 events × 3 groups each)');
            console.log('   ✅ Scenario 10 (No group props): 3 group identify events');
            console.log('   ✅ Scenario 11 (Mixed events): 3 group identify events');
            console.log('   ✅ Scenario 12 (Group edge cases): 6 group identify events (3 events × 2 groups each)');
            console.log('   ✅ Scenario 13 (Events before group identify): 2 group identify events');
            console.log('   ❌ Scenario 14 (Groups without identify): 0 group identify events');
            console.log('   🔄 Scenario 15 (Multiple updates): 8 group identify events (1 user, multiple updates)');
            console.log('   🏢 TOTAL EXPECTED: 38 group identify events\n');
        } else {
            console.log('📊 Expected Identify Events Summary:');
            console.log('   ✅ Scenario 1 (First-time): 5 identify events');
            console.log('   ✅ Scenario 2 (Duplicates): 3 identify events (only first occurrence)');
            console.log('   ✅ Scenario 3 (Multi-device): 4 identify events');
            console.log('   ✅ Scenario 4 (Multi-user): 4 identify events');
            console.log('   ✅ Scenario 5 (Edge cases): 8 identify events');
            console.log('   ✅ Scenario 6 (Anonymous→ID): 3 identify events');
            console.log('   ✅ Scenario 7 (Journey): 3 identify events (new devices only)');
            console.log('   📈 TOTAL EXPECTED: 30 identify events\n');

            console.log('🏢 Expected Group Identify Events Summary:');
            console.log('   ✅ Scenario 8 (Single groups): 4 group identify events');
            console.log('   ✅ Scenario 9 (Multiple groups): 12 group identify events (4 events × 3 groups each)');
            console.log('   ✅ Scenario 10 (No group props): 3 group identify events');
            console.log('   ✅ Scenario 11 (Mixed events): 3 group identify events');
            console.log('   ✅ Scenario 12 (Group edge cases): 6 group identify events (3 events × 2 groups each)');
            console.log('   ✅ Scenario 13 (Events before group identify): 2 group identify events');
            console.log('   ❌ Scenario 14 (Groups without identify): 0 group identify events');
            console.log('   🔄 Scenario 15 (Multiple updates): 8 group identify events (1 user, multiple updates)');
            console.log('   🏢 TOTAL EXPECTED: 38 group identify events\n');
        }

        console.log('📋 Key Test Cases:');
        console.log('   🔹 Groups with rich properties vs minimal properties');
        console.log('   🔹 Multiple groups per event (company + team + department)');
        console.log('   🔹 Groups without group_properties field');
        console.log('   🔹 Mixed events (some with groups, some without)');
        console.log('   🔹 Unicode and special characters in group names');
        console.log('   🔹 User events referencing groups BEFORE group identify events');
        console.log('   🔹 Events with groups but NO corresponding group identify events');
        console.log('   🔹 Single user with multiple group property updates over time');
        console.log('   🔹 Events with $groups property should be preserved\n');

        console.log('Next steps:');
        console.log('1. Review the generated data in amplitude-test-data.json');
        console.log('2. The script automatically sends both regular events AND group identify events to Amplitude');
        console.log('3. Export this data from Amplitude using their export API');
        if (groupsOnly) {
            console.log('4. Run PostHog batch import with generate_group_identify_events=true');
            console.log('5. Verify exactly 38 group identify events are created');
        } else {
            console.log('4. Run PostHog batch import with generate_identify_events=true and generate_group_identify_events=true');
            console.log('5. Verify exactly 30 identify events + 38 group identify events are created');
        }
        console.log('6. Check that regular events have $groups property with correct group references');
        console.log('7. Verify group properties are correctly mapped to PostHog $group_set\n');

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
