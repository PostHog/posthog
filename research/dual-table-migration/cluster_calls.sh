#!/bin/bash

# Cluster ORM calls by method type

echo "=== PERSON.OBJECTS METHOD CLUSTERING ==="
echo ""

echo "## Person.objects.get() calls:"
rg "Person\.objects.*\.get\(" posthog --type py -g '!test*' -g '!migrations' -n | wc -l
rg "Person\.objects.*\.get\(" posthog --type py -g '!test*' -g '!migrations' -n

echo ""
echo "## Person.objects.filter() calls:"
rg "Person\.objects.*\.filter\(" posthog --type py -g '!test*' -g '!migrations' -n | wc -l
rg "Person\.objects.*\.filter\(" posthog --type py -g '!test*' -g '!migrations' -n

echo ""
echo "## Person.objects.bulk_create() calls:"
rg "Person\.objects\.bulk_create\(" posthog --type py -g '!test*' -g '!migrations' -n | wc -l
rg "Person\.objects\.bulk_create\(" posthog --type py -g '!test*' -g '!migrations' -n

echo ""
echo "## Person.objects.create() calls:"
rg "Person\.objects\.create\(" posthog --type py -g '!test*' -g '!migrations' -n | wc -l
rg "Person\.objects\.create\(" posthog --type py -g '!test*' -g '!migrations' -n

echo ""
echo "## Person.objects.all() calls:"
rg "Person\.objects\.all\(" posthog --type py -g '!test*' -g '!migrations' -n | wc -l
rg "Person\.objects\.all\(" posthog --type py -g '!test*' -g '!migrations' -n

echo ""
echo "## Person.objects.db_manager() calls:"
rg "Person\.objects\.db_manager\(" posthog --type py -g '!test*' -g '!migrations' -n | wc -l
rg "Person\.objects\.db_manager\(" posthog --type py -g '!test*' -g '!migrations' -n

echo ""
echo ""
echo "=== PERSONDISTINCTID FK RELATION CLUSTERING ==="
echo ""

echo "## persondistinctid__distinct_id queries:"
rg "persondistinctid__distinct_id" posthog --type py -g '!test*' -g '!migrations' -n | wc -l
rg "persondistinctid__distinct_id" posthog --type py -g '!test*' -g '!migrations' -n

echo ""
echo "## persondistinctid_set prefetch:"
rg "persondistinctid_set" posthog --type py -g '!test*' -g '!migrations' -n | wc -l
rg "persondistinctid_set" posthog --type py -g '!test*' -g '!migrations' -n

echo ""
echo ""
echo "=== PERSONDISTINCTID.OBJECTS METHOD CLUSTERING ==="
echo ""

echo "## PersonDistinctId.objects.filter() calls:"
rg "PersonDistinctId\.objects.*\.filter\(" posthog --type py -g '!test*' -g '!migrations' -n | wc -l
rg "PersonDistinctId\.objects.*\.filter\(" posthog --type py -g '!test*' -g '!migrations' -n

echo ""
echo "## PersonDistinctId.objects.bulk_create() calls:"
rg "PersonDistinctId\.objects\.bulk_create\(" posthog --type py -g '!test*' -g '!migrations' -n | wc -l
rg "PersonDistinctId\.objects\.bulk_create\(" posthog --type py -g '!test*' -g '!migrations' -n

echo ""
echo "## PersonDistinctId.objects.create() calls:"
rg "PersonDistinctId\.objects\.create\(" posthog --type py -g '!test*' -g '!migrations' -n | wc -l
rg "PersonDistinctId\.objects\.create\(" posthog --type py -g '!test*' -g '!migrations' -n

