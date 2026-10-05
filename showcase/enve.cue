package devshell

import (
	"github.com/tonky/enve/pkgs:pkgs"
	schema "github.com/tonky/enve/schema/v1:schema"
)

// PostHog Analytics Polyglot Monorepo
// Zero-Daemon Rootless Developer Environment & Microservice Topology
devEnv: {
	name:        "posthog-monorepo"
	description: "PostHog Polyglot Monorepo (Django + Rust Capture + ClickHouse + Kafka + Temporal + SeaweedFS)"

	tools: [
		pkgs.seaweedfs,
		"python311",
		"uv",
		"clickhouse",
		"postgresql_15",
		"redis",
		"temporal",
		"tansu",
	]

	environment: {
		DATABASE_URL:              "postgres://posthog:posthog@127.0.0.1:15432/posthog"
		DAGSTER_TEST_POSTGRES_URL: "postgresql://posthog:posthog@127.0.0.1:15432/test_dagster"
		PGPORT:                    "15432"
		REDIS_URL:                 "redis://127.0.0.1:16379"
		REDIS_PORT:                "16379"
		CLICKHOUSE_HOST:           "127.0.0.1"
		CLICKHOUSE_HTTP_PORT:      "8123"
		CLICKHOUSE_TCP_PORT:       "9000"
		CLICKHOUSE_POSTGRES_HOST:  "127.0.0.1"
		CLICKHOUSE_POSTGRES_PORT:  "15432"
		PERSON_ON_EVENTS_V2_ENABLED: "true"
		KAFKA_HOSTS:               "127.0.0.1:19092"
		TEMPORAL_HOST:             "127.0.0.1"
		TEMPORAL_PORT:             "7233"
		CAPTURE_PORT:              "18000"
		OBJECT_STORAGE_ENABLED:            "True"
		OBJECT_STORAGE_ENDPOINT:           "http://127.0.0.1:19000"
		OBJECT_STORAGE_ACCESS_KEY_ID:      "object_storage_root_user"
		OBJECT_STORAGE_SECRET_ACCESS_KEY:  "object_storage_root_password"
		NOTEBOOKS_FRAME_STORE_S3_ENDPOINT: "http://127.0.0.1:19000"
	}

	services: {
		postgres: {
			name:    "postgres"
			command: "postgres -D /dev/shm/posthog_pg_15432 -h 127.0.0.1 -p 15432 -k /tmp -c listen_addresses=127.0.0.1 -c fsync=off"
			port:    15432
			dataDir: "/dev/shm/posthog_pg_15432"
			environment: {
				DATA_DIR: "/dev/shm/posthog_pg_15432"
			}
			lifecycle: init: [
				"test -f /dev/shm/posthog_pg_15432/PG_VERSION || { initdb -D /dev/shm/posthog_pg_15432 --auth=trust --username=posthog --no-sync && echo 'CREATE ROLE postgres SUPERUSER LOGIN;' | postgres --single -D /dev/shm/posthog_pg_15432 template1 && echo 'CREATE DATABASE posthog;' | postgres --single -D /dev/shm/posthog_pg_15432 template1 && echo 'CREATE DATABASE test_posthog;' | postgres --single -D /dev/shm/posthog_pg_15432 template1 && echo 'CREATE DATABASE test_posthog_persons;' | postgres --single -D /dev/shm/posthog_pg_15432 template1; }",
			]
			readinessProbe: {
				port:      15432
				timeoutMs: 5000
			}
		}

		redis: {
			name:    "redis"
			command: "redis-server --port 16379 --save '' --appendonly no"
			port:    16379
			readinessProbe: {
				port:      16379
				timeoutMs: 3000
			}
		}

		clickhouse: {
			name:      "clickhouse"
			command:   "clickhouse-server --config-file config/clickhouse.xml"
			port:      8123
			dependsOn: ["kafka"]
			environment: {
				CLICKHOUSE_DATA_DIR:            "/dev/shm/clickhouse/data/"
				CLICKHOUSE_TMP_DIR:             "/dev/shm/clickhouse/tmp/"
				CLICKHOUSE_USER_FILES_DIR:      "/dev/shm/clickhouse/user_files/"
				CLICKHOUSE_FORMAT_SCHEMA_DIR:   "/dev/shm/clickhouse/format_schemas/"
				CLICKHOUSE_ACCESS_DIR:          "/dev/shm/clickhouse/access/"
				CLICKHOUSE_KEEPER_LOG_DIR:      "/dev/shm/clickhouse/keeper/log/"
				CLICKHOUSE_KEEPER_SNAPSHOT_DIR: "/dev/shm/clickhouse/keeper/snapshots/"
				KAFKA_HOSTS:                    "127.0.0.1:19092"
			}
			lifecycle: init: [
				"mkdir -p /dev/shm/clickhouse/data && ln -sf $(git rev-parse --show-toplevel)/posthog/user_scripts /dev/shm/clickhouse/data/user_scripts",
			]
			healthCheck: {
				port:      8123
				path:      "http://127.0.0.1:8123/ping"
				timeoutMs: 10000
			}
			readinessProbe: {
				port:      8123
				timeoutMs: 10000
			}
		}

		kafka: {
			name:    "kafka"
			command: "tansu --listener-url tcp://127.0.0.1:19092 --advertised-listener-url tcp://127.0.0.1:19092 --storage-engine memory://tansu/"
			port:    19092
			readinessProbe: {
				port:      19092
				timeoutMs: 3000
			}
			lifecycle: postStart: [
				"sh -c 'PYTHON=$(test -f .venv/bin/python && echo .venv/bin/python || echo ../.venv/bin/python); SCRIPT=$(test -f showcase/scripts/create_test_kafka_topics.py && echo showcase/scripts/create_test_kafka_topics.py || echo scripts/create_test_kafka_topics.py); \"$PYTHON\" \"$SCRIPT\" || true'",
			]
		}

		temporal: {
			name:    "temporal"
			command: "temporal server start-dev --ip 127.0.0.1 --port 7233 --headless"
			port:    7233
			readinessProbe: {
				port:      7233
				timeoutMs: 5000
			}
		}

		capture: {
			name:      "capture"
			command:   "cargo run --manifest-path services/capture/Cargo.toml"
			port:      18000
			dependsOn: ["redis", "redpanda", "clickhouse"]
			readinessProbe: {
				port:      18000
				timeoutMs: 5000
			}
		}

		objectstorage: {
			name:    "objectstorage"
			command: "weed mini -ip=127.0.0.1 -ip.bind=127.0.0.1 -dir=/dev/shm/posthog_s3_19000 -s3.port=19000 -bucket=posthog,test-posthog,posthog-recordings,test-recordings"
			port:    19000
			environment: {
				AWS_ACCESS_KEY_ID:     "object_storage_root_user"
				AWS_SECRET_ACCESS_KEY: "object_storage_root_password"
				S3_BUCKET:             "posthog,test-posthog,posthog-recordings,test-recordings"
			}
			readinessProbe: {
				port:      19000
				timeoutMs: 5000
			}
		}
	}

	shellHook: """
		echo "🦔 Welcome to PostHog Monorepo (Zero-Daemon enve environment)"
		echo "Run 'enve up' to start background microservices in <1.2s"
		echo "Run 'enve up postgres redis' for minimal web API hacking"
		"""
}
