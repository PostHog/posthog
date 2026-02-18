#!/usr/bin/env python
import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
django.setup()

from products.data_warehouse.backend.models import DataWarehouseSavedQuery
from products.data_warehouse.backend.models.datawarehouse_managed_viewset import DataWarehouseManagedViewSet

# Check current views
views = DataWarehouseSavedQuery.objects.filter(team_id=1)
print(f"Current views for team 1: {views.count()}")
for v in views:
    print(f"  - {v.name}")

# Resync managed viewset
print("\nResyncing managed viewset...")
viewset = DataWarehouseManagedViewSet.objects.get(team_id=1)
viewset.sync_views()
print("Done!")

# Check views again
views = DataWarehouseSavedQuery.objects.filter(team_id=1)
print(f"\nViews after resync: {views.count()}")
for v in views:
    print(f"  - {v.name}")
