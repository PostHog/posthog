package schema

#Output: {
	path:      string
	hashAlgo?: string
	hash?:     string
}

#Port:             int & > 0 & <= 65535
#UnprivilegedPort: int & > 1024 & <= 65535

#Derivation: {
	pname:   string
	version: string
	name:    "\(pname)-\(version)"
	builder: string
	args?: [...string]
	env?: [string]: _
	inputDrvs?: [string]: _
	outputs: [string]: #Output
}

#BuildSpec: {
	pname:          string
	version:        string
	src:            string
	subPackages?:   _
	ldflags?:       _
	npmFlags?:      _
	nodeVersion?:   _
	packageJson?:   _
	packageLock?:   _
	buildScript?:   _
	format?:        _
	pythonVersion?: _
	features?:      _
	cargoFlags?:    _
	target?:        _
	erlangVersion?: _
	environment?:   _
	[string]:       _
}

#PackageRef: string | {
	pname:    string
	version?: string
}

#ServiceHealthCheck: {
	port?:       #Port
	path?:       string
	command?:    string
	intervalMs?: int & > 0 | *10000
	timeoutMs?:  int & > 0 | *3000
	retries?:    int & > 0 | *3
}

#ServiceReadinessProbe: {
	port?:           #Port
	path?:           string
	command?:        string
	initialDelayMs?: int & >= 0 | *0
	timeoutMs?:      int & > 0 | *3000
}

#ServiceFile: {
	target?:  string
	content?: string
	source?:  string
	mode?:    string | *"0644"
}

#ServiceLifecycle: {
	init?:      [...string]
	preStart?:  [...string]
	postStart?: [...string]
}

#ServiceResources: {
	cpu?:         string | float | int
	ram?:         string | float | int
	cpuPercent?:  float | int
	ramMb?:       float | int
	startupMs?:   int & >= 0
	healthMs?:    int & >= 0
	readinessMs?: int & >= 0
	[string]:     _
}

#Service: {
	name?:           string
	image?:          string
	command?:        string
	build?:          #BuildSpec
	directory?:      string
	dataDir?:        string
	files?:          [string]: #ServiceFile | string
	lifecycle?:      #ServiceLifecycle
	port?:           #Port
	timeoutMs?:      int & > 0 | *3000
	environment?:    [string]: _
	dependsOn?:      [...string]
	volumes?:        [...string]
	healthCheck?:    #ServiceHealthCheck
	readinessProbe?: #ServiceReadinessProbe
	restartPolicy?:  "always" | "on-failure" | "never" | *"on-failure"
	resources?:      #ServiceResources
	[string]:        _
}

#GitHooks: {
	cue_fmt?:       bool | *false
	clippy?:        bool | *false
	prettier?:      bool | *false
	ruff?:          bool | *false
	golangci_lint?: bool | *false
	custom?:        [string]: string
}

#RuntimeMap: {
	go?:     _
	rust?:   _
	node?:   _
	python?: _
	ruby?:   _
	gleam?:  _
	erlang?: _
	zig?:    _
	roc?:    _
	elixir?: _
	[string]: _
}

#PostgresService: #Service & {
	let defaultPort = 5432
	let defaultDataDir = ".enve/data/postgres"
	let defaultDb = "postgres"
	let defaultUser = "postgres"
	let defaultSocketDir = "/tmp"
	let defaultTimeoutMs = 2500

	port:        #Port | *defaultPort
	dataDir:     string | *defaultDataDir
	socketDir:   string | *defaultSocketDir
	database:    string | *defaultDb
	user:        string | *defaultUser
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"postgres -D \(defaultDataDir) -k \(defaultSocketDir) -p \(defaultPort)"
	lifecycle: {
		init: [
			*"initdb -D $DATA_DIR --auth-local=trust --auth-host=trust" | string,
		]
	}
	environment: {
		PGDATA:       defaultDataDir
		PGPORT:       "\(defaultPort)"
		PGHOST:       defaultSocketDir
		PGUSER:       defaultUser
		DATABASE_URL: "postgresql://\(defaultUser)@localhost:\(defaultPort)/\(defaultDb)"
	}
	healthCheck: {
		port:      #Port | *defaultPort
		command:   string | *"pg_isready -h 127.0.0.1 -p \(defaultPort) -U \(defaultUser)"
		timeoutMs: int | *1000
	}
	readinessProbe: {
		port:      #Port | *defaultPort
		command:   string | *"psql -h 127.0.0.1 -p \(defaultPort) -U \(defaultUser) -d \(defaultDb) -c 'SELECT 1;'"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#RedisService: #Service & {
	let defaultPort = 6379
	let defaultDataDir = ".enve/data/redis"
	let defaultTimeoutMs = 1500

	port:        #Port | *defaultPort
	dataDir:     string | *defaultDataDir
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"redis-server --port \(defaultPort) --dir \(defaultDataDir) --daemonize no"
	environment: {
		REDIS_PORT: "\(defaultPort)"
		REDIS_URL:  "redis://localhost:\(defaultPort)/0"
	}
	healthCheck: {
		port:      #Port | *defaultPort
		timeoutMs: int | *800
	}
	readinessProbe: {
		port:      #Port | *defaultPort
		command:   string | *"redis-cli -p \(defaultPort) ping"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#MySQLService: #Service & {
	let defaultPort = 3306
	let defaultDataDir = ".enve/data/mysql"
	let defaultTimeoutMs = 3500

	port:        #Port | *defaultPort
	dataDir:     string | *defaultDataDir
	timeoutMs:   int | *defaultTimeoutMs
	lifecycle: {
		init: [
			*"mysqld --initialize-insecure --datadir=\"$DATA_DIR\"" | string,
		]
	}
	command:     string | *"mysqld --datadir=\(defaultDataDir) --port=\(defaultPort)"
	environment: {
		MYSQL_TCP_PORT: "\(defaultPort)"
	}
	healthCheck: {
		port:      #Port | *defaultPort
		timeoutMs: int | *1500
	}
	readinessProbe: {
		port:      #Port | *defaultPort
		command:   string | *"mysqladmin ping -h 127.0.0.1 -P \(defaultPort)"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#ClickHouseService: #Service & {
	let defaultHttpPort = 8123
	let defaultTcpPort = 9000
	let defaultDataDir = ".enve/data/clickhouse"
	let defaultConfigFile = ".enve/config/clickhouse/config.xml"
	let defaultTimeoutMs = 3500

	port:        #Port | *defaultHttpPort
	tcpPort:     #Port | *defaultTcpPort
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
		port:      #Port | *defaultHttpPort
		path:      string | *"http://127.0.0.1:\(defaultHttpPort)/ping"
		timeoutMs: int | *1000
	}
	readinessProbe: {
		port:      #Port | *defaultHttpPort
		command:   string | *"curl -s -f 'http://127.0.0.1:\(defaultHttpPort)/?query=SELECT+1'"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#TemporalService: #Service & {
	let defaultPort = 7233
	let defaultDataDir = ".enve/data/temporal"
	let defaultDbFilename = ".enve/data/temporal/temporal.db"
	let defaultTimeoutMs = 2500

	port:        #Port | *defaultPort
	dataDir:     string | *defaultDataDir
	dbFilename:  string | *defaultDbFilename
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"temporal server start-dev --port \(defaultPort) --headless --db-filename \(defaultDbFilename)"
	environment: {
		TEMPORAL_PORT: "\(defaultPort)"
		TEMPORAL_HOST: "127.0.0.1"
	}
	healthCheck: {
		port:      #Port | *defaultPort
		timeoutMs: int | *1000
	}
	readinessProbe: {
		port:      #Port | *defaultPort
		command:   string | *"temporal operator cluster health --address 127.0.0.1:\(defaultPort)"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#SeaweedfsService: #Service & {
	let defaultPort = 19000
	let defaultDataDir = ".enve/data/seaweedfs"
	let defaultTimeoutMs = 6000

	port:        #Port | *defaultPort
	dataDir:     string | *defaultDataDir
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"weed server -s3 -s3.port=\(defaultPort) -dir=\(defaultDataDir)"
	environment: {
		S3_PORT:     "\(defaultPort)"
		S3_ENDPOINT: "http://127.0.0.1:\(defaultPort)"
	}
	healthCheck: {
		port:      #Port | *defaultPort
		timeoutMs: int | *4000
	}
	readinessProbe: {
		port:      #Port | *defaultPort
		command:   string | *"curl -s -f -o /dev/null http://127.0.0.1:\(defaultPort)/"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#NginxService: #Service & {
	let defaultPort = 8080
	let defaultConfigFile = "/etc/nginx/nginx.conf"
	let defaultRunDir = ".enve/data/nginx"
	let defaultTimeoutMs = 2000

	port:          #Port | *defaultPort
	configFile:    string | *defaultConfigFile
	runDir:        string | *defaultRunDir
	timeoutMs:     int | *defaultTimeoutMs
	command:       string | *"nginx -p \(defaultRunDir) -c \(defaultConfigFile) -g 'daemon off;'"
	healthCheck: {
		port:      #Port | *defaultPort
		timeoutMs: int | *1000
	}
	readinessProbe: {
		port:      #Port | *defaultPort
		path:      string | *"http://127.0.0.1:\(defaultPort)/"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#MinioService: #Service & {
	let defaultPort = 9000
	let defaultConsolePort = 9001
	let defaultDataDir = ".enve/data/minio"
	let defaultTimeoutMs = 3000

	port:               #Port | *defaultPort
	consolePort:        #Port | *defaultConsolePort
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
		port:      #Port | *defaultPort
		path:      string | *"http://127.0.0.1:\(defaultPort)/minio/health/live"
		timeoutMs: int | *1500
	}
	readinessProbe: {
		port:      #Port | *defaultPort
		path:      string | *"http://127.0.0.1:\(defaultPort)/minio/health/ready"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#RedpandaService: #Service & {
	let defaultKafkaPort = 9092
	let defaultAdminPort = 9644
	let defaultDataDir = ".enve/data/redpanda"
	let defaultTimeoutMs = 4000

	port:        #Port | *defaultKafkaPort
	adminPort:   #Port | *defaultAdminPort
	dataDir:     string | *defaultDataDir
	timeoutMs:   int | *defaultTimeoutMs
	command:     string | *"redpanda start --mode dev-container --kafka-addr 127.0.0.1:\(defaultKafkaPort) --admin-addr 127.0.0.1:\(defaultAdminPort) --dir \(defaultDataDir) --smp 1 --memory 512M --reserve-memory 0M --check=false"
	environment: {
		KAFKA_PORT:     "\(defaultKafkaPort)"
		KAFKA_BROKERS:  "127.0.0.1:\(defaultKafkaPort)"
		REDPANDA_ADMIN: "127.0.0.1:\(defaultAdminPort)"
	}
	healthCheck: {
		port:      #Port | *defaultKafkaPort
		timeoutMs: int | *1500
	}
	readinessProbe: {
		port:      #Port | *defaultAdminPort
		path:      string | *"http://127.0.0.1:\(defaultAdminPort)/v1/cluster/ready"
		timeoutMs: int | *defaultTimeoutMs
	}
}

#KafkaService: #RedpandaService

#DevEnvironment: {
	name?:        string | *""
	build?:       #BuildSpec
	tools?:       [..._] | *[]
	runtimes?:    #RuntimeMap
	services?:    [string]: #Service
	ports?:       [...#Port]
	gitHooks?:    #GitHooks
	environment?: [string]: _
	shellHook?:   string
	resources?:   _
	telemetry?:   _
	[string]:     _
}

#CueOnlyDevEnvironment: {
	name?:        string | *""
	build?:       #BuildSpec
	tools?:       [..._] | *[]
	runtimes?:    #RuntimeMap
	services?:    [string]: #Service
	ports?:       [...#Port]
	gitHooks?:    #GitHooks
	environment?: [string]: _
	shellHook?:   string
	resources?:   _
	telemetry?:   _
	[string]:     _
}

#GoBuildSpec: #BuildSpec
#NodeBuildSpec: #BuildSpec
#PythonBuildSpec: #BuildSpec
#RustBuildSpec: #BuildSpec
#GleamBuildSpec: #BuildSpec
#ErlangBuildSpec: #BuildSpec

// Canonical aliases
#Environment: #DevEnvironment
#Enve:        #DevEnvironment

