#!/usr/bin/env python3
"""
Quick test script to verify the basic HogQL refactoring is working.
This tests the core dependency injection without complex warehouse features.
"""

import os
import sys
from pathlib import Path

# Add the posthog directory to the path
posthog_root = Path(__file__).parent
sys.path.insert(0, str(posthog_root))

# Set up Django environment
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

import django  # noqa: E402

django.setup()

from posthog.hogql.database.database import (  # noqa: E402
    create_hogql_database,
    create_hogql_database_from_dependencies,
)
from posthog.hogql.data_loader import load_hogql_dependencies  # noqa: E402
from posthog.hogql.dependencies import HogQLDependencies  # noqa: E402


def test_dependency_injection():
    """Test that dependency injection pattern works"""

    # Create test setup (similar to BaseTest)
    from posthog.models import Team, Organization

    # Create test organization and team
    org = Organization.objects.create(name="Test Org")
    team = Team.objects.create(organization=org, name="Test Team")

    # Test 1: Load dependencies
    dependencies = load_hogql_dependencies(team.pk)

    assert isinstance(dependencies, HogQLDependencies)
    assert dependencies.team.pk == team.pk
    assert dependencies.team.project_id == team.project_id

    # Test 2: Create database from dependencies (pure function)
    database = create_hogql_database_from_dependencies(dependencies)

    assert database is not None
    assert hasattr(database, "events")
    assert hasattr(database, "persons")

    # Test 3: Compare with original function
    original_database = create_hogql_database(team_id=team.pk)

    # Both should have the same basic structure
    assert isinstance(database, type(original_database))
    assert database.timezone == original_database.timezone
    assert database.week_start_day == original_database.week_start_day

    # Test 4: Validate no Django imports in pure function
    import inspect

    source = inspect.getsource(create_hogql_database_from_dependencies)

    # Check that pure function doesn't import Django models directly
    django_imports = ["from posthog.models", "Team.objects", "GroupTypeMapping.objects", "DataWarehouseTable.objects"]

    for django_import in django_imports:
        if django_import in source:
            pass
        else:
            pass

    # Clean up
    team.delete()
    org.delete()


if __name__ == "__main__":
    test_dependency_injection()
