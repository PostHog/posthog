package pkgs

import devshell "github.com/tonky/enve/schema/v1:schema"

// -------------------------------------------------------------
// Local Developer Services, Databases & Container Tools
// -------------------------------------------------------------

postgres: devshell.#RustBuildSpec & {
	pname:   "postgresql"
	version: "17.4"
	src:     "https://ftp.postgresql.org/pub/source/v17.4/postgresql-17.4.tar.gz"
}

postgresql: postgres
postgresql_17: postgres
postgresql_16: devshell.#RustBuildSpec & {
	pname:   "postgresql"
	version: "16.4"
	src:     "https://ftp.postgresql.org/pub/source/v16.4/postgresql-16.4.tar.gz"
}
postgresql_15: devshell.#RustBuildSpec & {
	pname:   "postgresql"
	version: "15.8"
	src:     "https://ftp.postgresql.org/pub/source/v15.8/postgresql-15.8.tar.gz"
}
postgresql_14: devshell.#RustBuildSpec & {
	pname:   "postgresql"
	version: "14.13"
	src:     "https://ftp.postgresql.org/pub/source/v14.13/postgresql-14.13.tar.gz"
}

redis: devshell.#RustBuildSpec & {
	pname:   "redis"
	version: "7.4.2"
	src:     "https://github.com/redis/redis/archive/refs/tags/7.4.2.tar.gz"
}

docker_compose: devshell.#GoBuildSpec & {
	pname:       "docker-compose"
	version:     "2.33.1"
	src:         "https://github.com/docker/compose/archive/refs/tags/v2.33.1.tar.gz"
	subPackages: "cmd"
}

mysql: devshell.#RustBuildSpec & {
	pname:   "mysql"
	version: "8.4.0"
	src:     "https://github.com/mysql/mysql-server/archive/refs/tags/mysql-8.4.0.tar.gz"
}

minio: devshell.#GoBuildSpec & {
	pname:       "minio"
	version:     "2025.2.7"
	src:         "https://github.com/minio/minio/archive/refs/tags/RELEASE.2025-02-07T23-21-09Z.tar.gz"
	subPackages: "."
}

mailpit: devshell.#GoBuildSpec & {
	pname:       "mailpit"
	version:     "1.21.8"
	src:         "https://github.com/axllent/mailpit/archive/refs/tags/v1.21.8.tar.gz"
	subPackages: "."
}

clickhouse: devshell.#RustBuildSpec & {
	pname:   "clickhouse"
	version: "26.1"
	src:     "https://github.com/ClickHouse/ClickHouse/archive/refs/tags/v26.1.1.1-stable.tar.gz"
}

temporal: devshell.#RustBuildSpec & {
	pname:   "temporal-cli"
	version: "1.2.0"
	src:     "https://github.com/temporalio/cli/archive/refs/tags/v1.2.0.tar.gz"
}

seaweedfs: devshell.#GoBuildSpec & {
	pname:       "seaweedfs"
	version:     "3.84"
	src:         "https://github.com/seaweedfs/seaweedfs/archive/refs/tags/3.84.tar.gz"
	subPackages: "."
}

redpanda: devshell.#GoBuildSpec & {
	pname:       "redpanda"
	version:     "24.3.4"
	src:         "https://github.com/redpanda-data/redpanda/archive/refs/tags/v24.3.4.tar.gz"
	subPackages: "src/go/rpk"
}

rpk: redpanda

tansu: devshell.#RustBuildSpec & {
	pname:   "tansu"
	version: "0.6.0-pre.9"
	src:     "https://github.com/nisshi-io/nisshi/archive/refs/tags/v0.6.0-pre.9.tar.gz"
}

kafka: tansu

// -------------------------------------------------------------
// High-Level Microservice & Daemon Presets (#Service presets)
// -------------------------------------------------------------

#PostgresService: devshell.#Service & {
	let defaultPort = 5432
	let defaultDataDir = ".enve/data/postgres"
	let defaultDb = "postgres"
	let defaultUser = "postgres"
	let defaultTimeoutMs = 2500

	port:        devshell.#Port | *defaultPort
	dataDir:     string | *defaultDataDir
	database:    string | *defaultDb
	user:        string | *defaultUser
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"postgres -D \(defaultDataDir) -k /tmp -p \(defaultPort)"
	environment: {
		PGDATA:       defaultDataDir
		PGPORT:       "\(defaultPort)"
		PGHOST:       "/tmp"
		PGUSER:       defaultUser
		DATABASE_URL: "postgresql://\(defaultUser)@localhost:\(defaultPort)/\(defaultDb)"
	}
	healthCheck: {
		port:      devshell.#Port | *defaultPort
		command:   string | *"pg_isready -h 127.0.0.1 -p \(defaultPort) -U \(defaultUser)"
		timeoutMs: int | *defaultTimeoutMs
	}
	readinessProbe: {
		port:      devshell.#Port | *defaultPort
		command:   string | *"psql -h 127.0.0.1 -p \(defaultPort) -U \(defaultUser) -d \(defaultDb) -c 'SELECT 1;'"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#RedisService: devshell.#Service & {
	let defaultPort = 6379
	let defaultDataDir = ".enve/data/redis"
	let defaultTimeoutMs = 1500

	port:        devshell.#Port | *defaultPort
	dataDir:     string | *defaultDataDir
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"redis-server --port \(defaultPort) --dir \(defaultDataDir) --daemonize no"
	environment: {
		REDIS_PORT: "\(defaultPort)"
		REDIS_URL:  "redis://localhost:\(defaultPort)/0"
	}
	healthCheck: {
		port:      devshell.#Port | *defaultPort
		timeoutMs: int | *defaultTimeoutMs
	}
	readinessProbe: {
		port:      devshell.#Port | *defaultPort
		command:   string | *"redis-cli -p \(defaultPort) ping"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#MinioService: devshell.#Service & {
	let defaultPort = 9000
	let defaultConsolePort = 9001
	let defaultDataDir = ".enve/data/minio"
	let defaultTimeoutMs = 3000

	port:               devshell.#Port | *defaultPort
	consolePort:        devshell.#Port | *defaultConsolePort
	dataDir:            string | *defaultDataDir
	timeoutMs:          int | *defaultTimeoutMs
	command:            string | *"minio server \(defaultDataDir) --address :\(defaultPort) --console-address :\(defaultConsolePort)"
	environment: {
		MINIO_PORT:          "\(defaultPort)"
		MINIO_CONSOLE_PORT:  "\(defaultConsolePort)"
		MINIO_ROOT_USER:     "minioadmin"
		MINIO_ROOT_PASSWORD: "minioadmin"
		S3_ENDPOINT:         "http://localhost:\(defaultPort)"
	}
	healthCheck: {
		port:      devshell.#Port | *defaultPort
		path:      string | *"http://127.0.0.1:\(defaultPort)/minio/health/live"
		timeoutMs: int | *defaultTimeoutMs
	}
	readinessProbe: {
		port:      devshell.#Port | *defaultPort
		path:      string | *"http://127.0.0.1:\(defaultPort)/minio/health/ready"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#NginxService: devshell.#Service & {
	let defaultPort = 8080
	let defaultConfigFile = "/etc/nginx/nginx.conf"
	let defaultRunDir = ".enve/data/nginx"
	let defaultTimeoutMs = 2000

	port:          devshell.#Port | *defaultPort
	configFile:    string | *defaultConfigFile
	runDir:        string | *defaultRunDir
	timeoutMs:     int | *defaultTimeoutMs
	command:       string | *"nginx -p \(defaultRunDir) -c \(defaultConfigFile) -g 'daemon off;'"
	healthCheck: {
		port:      devshell.#Port | *defaultPort
		timeoutMs: int | *defaultTimeoutMs
	}
	readinessProbe: {
		port:      devshell.#Port | *defaultPort
		path:      string | *"http://127.0.0.1:\(defaultPort)/"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#MySQLService: devshell.#Service & {
	let defaultPort = 3306
	let defaultDataDir = ".enve/data/mysql"
	let defaultTimeoutMs = 3500

	port:        devshell.#Port | *defaultPort
	dataDir:     string | *defaultDataDir
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"mysqld --datadir=\(defaultDataDir) --port=\(defaultPort)"
	environment: {
		MYSQL_TCP_PORT: "\(defaultPort)"
	}
	healthCheck: {
		port:      devshell.#Port | *defaultPort
		timeoutMs: int | *defaultTimeoutMs
	}
	readinessProbe: {
		port:      devshell.#Port | *defaultPort
		command:   string | *"mysqladmin ping -h 127.0.0.1 -P \(defaultPort)"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#ClickHouseService: devshell.#Service & {
	let defaultHttpPort = 8123
	let defaultTcpPort = 9000
	let defaultDataDir = ".enve/data/clickhouse"
	let defaultConfigFile = ".enve/config/clickhouse/config.xml"
	let defaultTimeoutMs = 3500

	port:        devshell.#Port | *defaultHttpPort
	tcpPort:     devshell.#Port | *defaultTcpPort
	dataDir:     string | *defaultDataDir
	configFile:  string | *defaultConfigFile
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"clickhouse-server --config-file=\(defaultConfigFile)"
	environment: {
		CLICKHOUSE_DATA_DIR:  defaultDataDir
		CLICKHOUSE_HTTP_PORT: "\(defaultHttpPort)"
		CLICKHOUSE_TCP_PORT:  "\(defaultTcpPort)"
	}
	healthCheck: {
		port:      devshell.#Port | *defaultHttpPort
		path:      string | *"http://127.0.0.1:\(defaultHttpPort)/ping"
		timeoutMs: int | *defaultTimeoutMs
	}
	readinessProbe: {
		port:      devshell.#Port | *defaultHttpPort
		command:   string | *"curl -s -f 'http://127.0.0.1:\(defaultHttpPort)/?query=SELECT+1'"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#TemporalService: devshell.#Service & {
	let defaultPort = 7233
	let defaultDataDir = ".enve/data/temporal"
	let defaultDbFilename = ".enve/data/temporal/temporal.db"
	let defaultTimeoutMs = 2500

	port:        devshell.#Port | *defaultPort
	dataDir:     string | *defaultDataDir
	dbFilename:  string | *defaultDbFilename
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"temporal server start-dev --port \(defaultPort) --headless --db-filename \(defaultDbFilename)"
	environment: {
		TEMPORAL_PORT: "\(defaultPort)"
		TEMPORAL_HOST: "127.0.0.1"
	}
	healthCheck: {
		port:      devshell.#Port | *defaultPort
		timeoutMs: int | *defaultTimeoutMs
	}
	readinessProbe: {
		port:      devshell.#Port | *defaultPort
		command:   string | *"temporal operator cluster health --address 127.0.0.1:\(defaultPort)"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#SeaweedfsService: devshell.#Service & {
	let defaultPort = 19000
	let defaultDataDir = ".enve/data/seaweedfs"
	let defaultTimeoutMs = 6000

	port:        devshell.#Port | *defaultPort
	dataDir:     string | *defaultDataDir
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"weed server -s3 -s3.port=\(defaultPort) -dir=\(defaultDataDir)"
	environment: {
		S3_PORT:     "\(defaultPort)"
		S3_ENDPOINT: "http://127.0.0.1:\(defaultPort)"
	}
	healthCheck: {
		port:      devshell.#Port | *defaultPort
		timeoutMs: int | *defaultTimeoutMs
	}
	readinessProbe: {
		port:      devshell.#Port | *defaultPort
		command:   string | *"curl -s -f -o /dev/null http://127.0.0.1:\(defaultPort)/"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#RedpandaService: devshell.#Service & {
	let defaultKafkaPort = 9092
	let defaultAdminPort = 9644
	let defaultDataDir = ".enve/data/redpanda"
	let defaultTimeoutMs = 4000

	port:        devshell.#Port | *defaultKafkaPort
	adminPort:   devshell.#Port | *defaultAdminPort
	dataDir:     string | *defaultDataDir
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"redpanda start --mode dev-container --kafka-addr 127.0.0.1:\(defaultKafkaPort) --admin-addr 127.0.0.1:\(defaultAdminPort) --dir \(defaultDataDir) --smp 1 --memory 512M --reserve-memory 0M --check=false"
	environment: {
		KAFKA_PORT:     "\(defaultKafkaPort)"
		KAFKA_BROKERS:  "127.0.0.1:\(defaultKafkaPort)"
		REDPANDA_ADMIN: "127.0.0.1:\(defaultAdminPort)"
	}
	healthCheck: {
		port:      devshell.#Port | *defaultKafkaPort
		timeoutMs: int | *1500
	}
	readinessProbe: {
		port:      devshell.#Port | *defaultAdminPort
		path:      string | *"http://127.0.0.1:\(defaultAdminPort)/v1/cluster/ready"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#TansuService: devshell.#Service & {
	let defaultPort = 9092
	let defaultEngine = "memory://tansu/"
	let defaultTimeoutMs = 1500

	port:          devshell.#Port | *defaultPort
	storageEngine: string | *defaultEngine
	timeoutMs:     int | *defaultTimeoutMs
	command:       string | *"tansu --listener-url tcp://127.0.0.1:\(defaultPort) --advertised-listener-url tcp://127.0.0.1:\(defaultPort) --storage-engine \(storageEngine)"
	environment: {
		KAFKA_PORT:    "\(defaultPort)"
		KAFKA_BROKERS: "127.0.0.1:\(defaultPort)"
	}
	healthCheck: {
		port:      devshell.#Port | *defaultPort
		timeoutMs: int | *800
	}
	readinessProbe: {
		port:      devshell.#Port | *defaultPort
		timeoutMs: int | *1000
	}
}

#KafkaService: #TansuService

