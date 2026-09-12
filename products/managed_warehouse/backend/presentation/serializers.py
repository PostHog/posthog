from rest_framework import serializers


class LocalWarehouseConnectionSerializer(serializers.Serializer):
    host = serializers.CharField()
    port = serializers.IntegerField()
    database = serializers.CharField()
    username = serializers.CharField()


class LocalWarehouseStatusSerializer(serializers.Serializer):
    org_id = serializers.CharField()
    state = serializers.CharField()
    status_message = serializers.CharField()
    s3_state = serializers.CharField()
    metadata_store_state = serializers.CharField()
    identity_state = serializers.CharField()
    secrets_state = serializers.CharField()
    ready_at = serializers.CharField(allow_null=True)
    failed_at = serializers.CharField(allow_null=True)
    connection = LocalWarehouseConnectionSerializer(allow_null=True)
    bucket = serializers.CharField(allow_null=True)
    bucket_region = serializers.CharField(allow_null=True)
    updated_at = serializers.CharField()


class LocalWarehouseStateSerializer(serializers.Serializer):
    state = serializers.CharField()


class LocalWarehouseLimitsSerializer(serializers.Serializer):
    max_workers = serializers.IntegerField()
    max_vcpus = serializers.IntegerField()
    default_worker_cpu = serializers.CharField()
    default_worker_memory = serializers.CharField()
    default_worker_ttl_seconds = serializers.IntegerField()
    default_worker_min_hot_idle = serializers.IntegerField()


class LocalWarehouseTotalsSerializer(serializers.Serializer):
    workers = serializers.IntegerField()
    allocated_cpu_cores = serializers.IntegerField()
    allocated_memory_bytes = serializers.IntegerField()
    active_sessions = serializers.IntegerField()
    running_queries = serializers.IntegerField()
    queued_connections = serializers.IntegerField()


class LocalWarehouseMonitoringSnapshotSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField()
    org_id = serializers.CharField()
    as_of = serializers.CharField()
    warehouse = LocalWarehouseStateSerializer()
    limits = LocalWarehouseLimitsSerializer()
    totals = LocalWarehouseTotalsSerializer()
    workers = serializers.ListField(child=serializers.DictField())
    coverage = serializers.DictField()


class LocalWarehouseMonitoringSeriesSerializer(serializers.Serializer):
    schema_version = serializers.IntegerField()
    org_id = serializers.CharField()
    metric = serializers.CharField()
    unit = serializers.CharField()
    start = serializers.CharField()
    end = serializers.CharField()
    step_seconds = serializers.IntegerField()
    series = serializers.ListField(child=serializers.DictField())


class LocalWarehouseNameAvailabilitySerializer(serializers.Serializer):
    name = serializers.CharField(allow_null=True)
    available = serializers.BooleanField()


class LocalWarehouseTeamsSerializer(serializers.Serializer):
    teams = serializers.ListField(child=serializers.DictField())
    data_imports_table_naming_version = serializers.CharField()


class LocalTrinoConnectionSerializer(serializers.Serializer):
    host = serializers.CharField()
    port = serializers.IntegerField()
    username = serializers.CharField()


class LocalTrinoStatusSerializer(serializers.Serializer):
    org = serializers.CharField()
    state = serializers.CharField()
    trino_catalog_name = serializers.CharField()
    connection = LocalTrinoConnectionSerializer()


class LocalTrinoResponseSerializer(serializers.Serializer):
    enabled = serializers.BooleanField()
    status = LocalTrinoStatusSerializer()


class LocalWarehousePasswordSerializer(serializers.Serializer):
    password = serializers.CharField()
