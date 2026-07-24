#!/usr/bin/env node

/**
 * Test script to validate a PostHog access token.
 *
 * Usage:
 *   node scripts/test-access-token.js <access_token> <project_id> [region]
 *
 * Examples:
 *   node scripts/test-access-token.js "your-access-token" 1
 *   node scripts/test-access-token.js "your-access-token" 1 us
 *   node scripts/test-access-token.js "your-access-token" 1 eu
 */

const CLOUD_URLS = {
  us: "https://us.posthog.com",
  eu: "https://eu.posthog.com",
  dev: "http://localhost:8010",
};

async function validateToken(token, region, projectId) {
  const cloudUrl = CLOUD_URLS[region];

  console.log(`\nValidating access token against ${cloudUrl}`);
  console.log(`Project ID: ${projectId}`);
  console.log("-".repeat(60));

  // Test 1: Get tasks
  console.log(
    `\n1. GET /api/projects/${projectId}/tasks/?limit=500&created_by=1`,
  );
  try {
    const response = await fetch(
      `${cloudUrl}/api/projects/${projectId}/tasks/?limit=500&created_by=1`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      },
    );

    if (!response.ok) {
      const text = await response.text();
      console.log(`   FAILED: ${response.status} ${response.statusText}`);
      console.log(`   ${text}`);
    } else {
      const data = await response.json();
      console.log(`   OK: ${data.results?.length || 0} tasks returned`);
    }
  } catch (error) {
    console.log(`   ERROR: ${error.message}`);
  }

  // Test 2: Get integrations
  console.log(`\n2. GET /api/environments/${projectId}/integrations/`);
  try {
    const response = await fetch(
      `${cloudUrl}/api/environments/${projectId}/integrations/`,
      {
        headers: {
          Authorization: `Bearer ${token}`,
          "Content-Type": "application/json",
        },
      },
    );

    if (!response.ok) {
      const text = await response.text();
      console.log(`   FAILED: ${response.status} ${response.statusText}`);
      console.log(`   ${text}`);
    } else {
      const data = await response.json();
      console.log(`   OK: ${data.results?.length || 0} integrations returned`);
    }
  } catch (error) {
    console.log(`   ERROR: ${error.message}`);
  }

  console.log(`\n${"-".repeat(60)}`);
}

// Main
const args = process.argv.slice(2);

if (args.length < 2) {
  console.log(
    "Usage: node scripts/test-access-token.js <access_token> <project_id> [region]",
  );
  console.log("");
  console.log("Arguments:");
  console.log("  access_token   Your OAuth access token");
  console.log("  project_id     Your PostHog project ID");
  console.log("  region         us, eu, or dev (default: us)");
  console.log("");
  console.log("Example:");
  console.log('  node scripts/test-access-token.js "your-access-token" 1 us');
  process.exit(1);
}

const token = args[0].replace(/^["']|["']$/g, "");
const projectId = args[1];
const region = args[2] || "us";

if (!CLOUD_URLS[region]) {
  console.error(`Invalid region: ${region}. Must be one of: us, eu, dev`);
  process.exit(1);
}

validateToken(token, region, projectId);
