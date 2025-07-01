#!/bin/bash

# Test script for migration conflict workflows
# This script creates test migration conflicts and triggers the workflows via API

set -e

echo "🧪 Migration Conflict Workflow Test Script"
echo "=========================================="

BRANCH="yasen/feat/migrations-conflict-resolution-in-ci"
PR_NUMBER="34406"

# Function to create test migration conflicts
create_test_conflicts() {
    echo "📝 Creating test migration conflicts..."
    
    # Create a test migration file that conflicts with master
    cat > posthog/migrations/0783_test_migration_conflict.py << 'EOF'
# Test migration file to trigger conflict detection workflow
# This is a temporary file for testing the new comment-based resolution system

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('posthog', '0782_previous_migration'),  # This will create a simulated conflict
    ]

    operations = [
        # Empty migration for testing purposes
    ]
EOF

    # Update max_migration.txt to point to our test migration
    echo "0783_test_migration_conflict" > posthog/migrations/max_migration.txt
    
    echo "✅ Test migration conflicts created"
}

# Function to remove test migration conflicts
cleanup_test_conflicts() {
    echo "🧹 Cleaning up test migration conflicts..."
    
    # Remove test migration file
    rm -f posthog/migrations/0783_test_migration_conflict.py
    
    # Restore max_migration.txt to master version
    git show origin/master:posthog/migrations/max_migration.txt > posthog/migrations/max_migration.txt
    
    echo "✅ Test migration conflicts cleaned up"
}

# Function to trigger auto-detect workflow
test_auto_detect() {
    echo "🔍 Testing auto-detection workflow..."
    
    gh api --method POST /repos/PostHog/posthog/dispatches \
        -f event_type="test-auto-detect" \
        -f client_payload="{\"branch\":\"$BRANCH\",\"pr_number\":$PR_NUMBER}"
    
    echo "✅ Auto-detect workflow triggered via repository_dispatch"
    echo "   Check: https://github.com/PostHog/posthog/actions"
}

# Function to trigger preview workflow
test_preview() {
    echo "🔍 Testing preview workflow..."
    
    gh api --method POST /repos/PostHog/posthog/dispatches \
        -f event_type="test-preview" \
        -f client_payload="{\"branch\":\"$BRANCH\",\"pr_number\":$PR_NUMBER,\"app_filter\":\"\"}"
    
    echo "✅ Preview workflow triggered via repository_dispatch"
    echo "   Check: https://github.com/PostHog/posthog/actions"
}

# Function to trigger apply workflow  
test_apply() {
    echo "🔧 Testing apply workflow..."
    
    gh api --method POST /repos/PostHog/posthog/dispatches \
        -f event_type="test-apply" \
        -f client_payload="{\"branch\":\"$BRANCH\",\"pr_number\":$PR_NUMBER,\"app_filter\":\"\"}"
    
    echo "✅ Apply workflow triggered via repository_dispatch"
    echo "   Check: https://github.com/PostHog/posthog/actions"
}

# Main test menu
case "${1:-menu}" in
    "setup")
        create_test_conflicts
        ;;
    "cleanup")
        cleanup_test_conflicts
        ;;
    "auto-detect"|"detect")
        test_auto_detect
        ;;
    "preview")
        test_preview
        ;;
    "apply"|"fix")
        test_apply
        ;;
    "full-test")
        echo "🚀 Running full workflow test..."
        create_test_conflicts
        git add . && git commit -m "test: add migration conflicts for workflow testing" || true
        git push origin $BRANCH || true
        echo "⏳ Waiting 5 seconds for push to register..."
        sleep 5
        test_auto_detect
        echo "⏳ Waiting 10 seconds before triggering preview..."
        sleep 10
        test_preview
        echo "✅ Full test completed. Check the PR for comments!"
        echo "   PR: https://github.com/PostHog/posthog/pull/$PR_NUMBER"
        ;;
    *)
        echo "Usage: ./test-migration-workflows.sh [command]"
        echo ""
        echo "Commands:"
        echo "  setup        Create test migration conflicts"
        echo "  cleanup      Remove test migration conflicts"
        echo "  detect       Trigger auto-detection workflow"
        echo "  preview      Trigger preview workflow"
        echo "  apply        Trigger apply workflow"
        echo "  full-test    Run complete test (setup + detect + preview)"
        echo ""
        echo "Examples:"
        echo "  ./test-migration-workflows.sh setup"
        echo "  ./test-migration-workflows.sh detect"
        echo "  ./test-migration-workflows.sh full-test"
        echo ""
        echo "Note: Workflows need to be available on master to be triggered."
        echo "Currently testing via repository_dispatch from feature branch."
        ;;
esac

echo ""
echo "🔗 Useful links:"
echo "   • PR: https://github.com/PostHog/posthog/pull/$PR_NUMBER"
echo "   • Actions: https://github.com/PostHog/posthog/actions"
echo "   • Workflows: https://github.com/PostHog/posthog/actions/workflows" 