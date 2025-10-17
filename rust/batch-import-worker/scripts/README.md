# Batch Import Worker Scripts

This directory contains test scripts and utilities for the PostHog Rust batch import worker.

## Amplitude Test Data Generator

Generates comprehensive test data for testing the PostHog Amplitude identify logic during batch imports.

**Features:**

- **Strictly Increasing Timestamps**: All events are generated with chronologically ordered timestamps to ensure proper data sequencing
- **Timestamp Verification**: Automatically validates that all generated events maintain strict temporal ordering
- **Configurable Time Ranges**: Support for custom time windows and historical data generation

### Installation

```bash
cd rust/batch-import-worker/scripts
npm install
```

### Usage

#### Generate Test Data

```bash
# Generate test data (saves to amplitude-test-data.json)
npm run generate

# Or run directly
node amplitude-test-generator.js
```

#### Send to Real Amplitude Instance

```bash
# US Cluster (default)
AMPLITUDE_API_KEY=your_real_api_key npm run generate

# EU Cluster
AMPLITUDE_API_KEY=your_real_api_key AMPLITUDE_CLUSTER=eu npm run generate
```

#### Custom Time Range

```bash
# Specify custom time range using environment variables
AMPLITUDE_START_TIME='2024-01-01T00:00:00Z' AMPLITUDE_END_TIME='2024-01-07T23:59:59Z' npm run generate

# Use relative time ranges
AMPLITUDE_START_TIME='1 week ago' AMPLITUDE_END_TIME='now' npm run generate

# Single day range
AMPLITUDE_START_TIME='2024-01-15' AMPLITUDE_END_TIME='2024-01-15T23:59:59Z' npm run generate

# Combined with API key and cluster
AMPLITUDE_API_KEY=your_key AMPLITUDE_CLUSTER=eu AMPLITUDE_START_TIME='2024-01-01' AMPLITUDE_END_TIME='2024-01-02' npm run generate
```

#### Environment Variables

- `AMPLITUDE_API_KEY`: Your Amplitude API key (required for sending to Amplitude)
- `AMPLITUDE_CLUSTER`: Choose 'us' (default) or 'eu' for the Amplitude cluster
- `AMPLITUDE_START_TIME`: Start timestamp for events (ISO format or relative, e.g., '2024-01-01T00:00:00Z', '1 week ago')
- `AMPLITUDE_END_TIME`: End timestamp for events (ISO format or relative, e.g., '2024-01-07T23:59:59Z', 'now')

**Note:** If no time range is specified, events will be generated for a 24-hour period starting from yesterday.

### Test Scenarios Covered

The generator creates **7 comprehensive scenarios** to test identify event logic:

1. **First-time combinations** (5 events) - Should generate identify events
2. **Duplicate combinations** (9 events) - Only first occurrence should generate identify
3. **Multi-device users** (4 events) - Same user across multiple devices
4. **Multi-user devices** (4 events) - Multiple users on same device
5. **Edge cases** (8 events) - Unicode, special chars, long IDs, etc.
6. **Anonymous→Identified** (9 events) - Device-only to user+device transitions
7. **Cross-session journeys** (6 events) - User switching devices over time

**Total: ~45 events, expecting exactly 30 identify events**

### Expected Identify Events

Based on the generated data, you should see identify events for:

- ✅ 5 first-time combinations (Scenario 1)
  - `first_time_user_alice` + `first_time_device_mobile_1`
  - `first_time_user_bob` + `first_time_device_laptop_2`
  - etc.
- ✅ 3 duplicate combinations (Scenario 2) - **only first occurrence**
  - `duplicate_user_frank` + `duplicate_device_phone_1` (first event only)
  - `duplicate_user_grace` + `duplicate_device_computer_2` (first event only)
  - `duplicate_user_henry` + `duplicate_device_ipad_3` (first event only)
- ✅ 4 multi-device user combinations (Scenario 3)
  - `multi_device_user_sarah` + each of 4 devices
- ✅ 4 multi-user device combinations (Scenario 4)
  - Each family member + `shared_family_tablet_main`
- ✅ 8 edge case combinations (Scenario 5)
  - `edge_unicode_用户` + `edge_unicode_设备`, etc.
- ✅ 3 anonymous-to-identified transitions (Scenario 6)
  - `anon_to_id_user_1` + `anon_device_phone_1` (when user first identifies)
- ✅ 3 cross-session journey devices (Scenario 7) - **new devices only**
  - `journey_user_alex` + `journey_phone_commute`, `journey_laptop_office`, `journey_tablet_home`

**Total Expected: 30 identify events from ~45 generated events**

### Key Logic Verification Points

1. **Deduplication:** Same user-device pair should only generate ONE identify event
2. **Validation:** Empty/null user_id or device_id should not generate identify events
3. **Unicode Support:** Non-ASCII characters in user/device IDs should work correctly
4. **Edge Cases:** Very long IDs, special characters, whitespace handling
5. **Anonymous Transitions:** Device-only events followed by identified events
6. **Cross-session Persistence:** User switching between known devices shouldn't create duplicates

### Testing Workflow

1. **Generate Test Data:**

   ```bash
   # US cluster (default) with default time range
   npm run generate

   # EU cluster
   AMPLITUDE_CLUSTER=eu npm run generate

   # With custom time range for specific migration window
   AMPLITUDE_START_TIME='2024-01-01' AMPLITUDE_END_TIME='2024-01-07' npm run generate
   ```

2. **Export from Amplitude:**
   Use Amplitude's export API to get the generated events in the format expected by PostHog batch imports. Make sure to use the same cluster (US/EU) that you sent the data to.

3. **Run PostHog Batch Import:**
   Create a batch import with:
   - Source: Amplitude
   - `generate_identify_events: true`
   - `import_events: true`

4. **Verify Results:**
   - Exactly 30 `$identify` events should be created
   - Each should have correct `$anon_distinct_id` (device_id) and `distinct_id` (user_id)
   - No duplicate identify events for same user-device combinations
   - Invalid cases should be handled gracefully

### Rust Integration

This test data generator is specifically designed to test the Rust batch import worker's identify logic found in:

- `src/parse/content/amplitude/identify.rs` - Identify event creation logic
- `src/parse/content/amplitude.rs` - Main Amplitude event parsing with identify injection
- `src/job/config.rs` - Job configuration including `generate_identify_events` flag

The generated test scenarios comprehensively cover the edge cases and logic paths in the Rust implementation.

### Output Files

- `amplitude-test-data.json` - Complete test dataset with metadata
- Console logs showing expected vs actual behavior for each scenario

### Extending

To add new test scenarios:

1. Add scenario-specific user/device names to `SCENARIO_USERS`/`SCENARIO_DEVICES`
2. Create a new `generate*()` method in `AmplitudeTestGenerator`
3. Call it from `generateAllScenarios()`
4. Update expected identify event count in the summary

### Dependencies

- `@amplitude/analytics-node` - Official Amplitude Node.js Analytics SDK for sending test events
- Node.js 16+ required
