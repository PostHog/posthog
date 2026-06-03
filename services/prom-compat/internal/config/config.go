// Package config loads prom-compat configuration from environment variables.
package config

import (
	"errors"
	"fmt"
	"os"
	"strconv"
	"time"
)

// Config is the full set of runtime configuration values.
type Config struct {
	Host string
	Port string

	ClickHouse ClickHouseConfig
}

// ClickHouseConfig describes how to connect to the logs ClickHouse cluster
// where the metrics1 table lives. The env var names mirror the Django
// settings in posthog/settings/data_stores.py so deployments can reuse the
// same secrets.
type ClickHouseConfig struct {
	Host         string
	Port         string
	User         string
	Password     string
	Database     string
	MaxOpenConns int
	MaxIdleConns int
	MaxLifetime  time.Duration
	DialTimeout  time.Duration
	ReadTimeout  time.Duration
}

// Load reads configuration from the process environment and returns an
// error if any required value is missing.
func Load() (*Config, error) {
	ch := ClickHouseConfig{
		Host:         os.Getenv("CLICKHOUSE_LOGS_CLUSTER_HOST"),
		Port:         envOrDefault("CLICKHOUSE_LOGS_CLUSTER_PORT", "9000"),
		User:         os.Getenv("CLICKHOUSE_LOGS_CLUSTER_USER"),
		Password:     os.Getenv("CLICKHOUSE_LOGS_CLUSTER_PASSWORD"),
		Database:     os.Getenv("CLICKHOUSE_LOGS_CLUSTER_DATABASE"),
		MaxOpenConns: envIntOrDefault("CH_MAX_OPEN_CONNS", 32),
		MaxIdleConns: envIntOrDefault("CH_MAX_IDLE_CONNS", 8),
		MaxLifetime:  envDurationOrDefault("CH_MAX_LIFETIME", time.Hour),
		DialTimeout:  envDurationOrDefault("CH_DIAL_TIMEOUT", 5*time.Second),
		ReadTimeout:  envDurationOrDefault("CH_READ_TIMEOUT", 30*time.Second),
	}
	var missing []string
	if ch.Host == "" {
		missing = append(missing, "CLICKHOUSE_LOGS_CLUSTER_HOST")
	}
	if ch.User == "" {
		missing = append(missing, "CLICKHOUSE_LOGS_CLUSTER_USER")
	}
	if ch.Database == "" {
		missing = append(missing, "CLICKHOUSE_LOGS_CLUSTER_DATABASE")
	}
	if len(missing) > 0 {
		return nil, fmt.Errorf("missing required env vars: %v", missing)
	}
	if ch.MaxOpenConns <= 0 || ch.MaxIdleConns < 0 || ch.MaxIdleConns > ch.MaxOpenConns {
		return nil, errors.New("CH_MAX_OPEN_CONNS must be > 0 and CH_MAX_IDLE_CONNS in [0, CH_MAX_OPEN_CONNS]")
	}
	return &Config{
		Host:       envOrDefault("HOST", "0.0.0.0"),
		Port:       envOrDefault("PORT", "9090"),
		ClickHouse: ch,
	}, nil
}

func envOrDefault(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

func envIntOrDefault(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func envDurationOrDefault(key string, def time.Duration) time.Duration {
	if v := os.Getenv(key); v != "" {
		if d, err := time.ParseDuration(v); err == nil {
			return d
		}
	}
	return def
}
