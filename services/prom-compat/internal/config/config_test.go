package config

import (
	"testing"
	"time"
)

func setRequired(t *testing.T) {
	t.Helper()
	t.Setenv("CLICKHOUSE_LOGS_CLUSTER_HOST", "ch.example")
	t.Setenv("CLICKHOUSE_LOGS_CLUSTER_USER", "default")
	t.Setenv("CLICKHOUSE_LOGS_CLUSTER_DATABASE", "default")
}

func TestLoadRejectsMissingRequiredEnv(t *testing.T) {
	t.Setenv("CLICKHOUSE_LOGS_CLUSTER_HOST", "")
	t.Setenv("CLICKHOUSE_LOGS_CLUSTER_USER", "")
	t.Setenv("CLICKHOUSE_LOGS_CLUSTER_DATABASE", "")
	if _, err := Load(); err == nil {
		t.Fatal("expected error when required env vars are missing")
	}
}

func TestLoadApplyDefaults(t *testing.T) {
	setRequired(t)
	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Host != "0.0.0.0" || cfg.Port != "9090" {
		t.Errorf("bind defaults: got %s:%s, want 0.0.0.0:9090", cfg.Host, cfg.Port)
	}
	if cfg.ClickHouse.Port != "9000" {
		t.Errorf("CH port default: got %s, want 9000", cfg.ClickHouse.Port)
	}
	if cfg.ClickHouse.MaxOpenConns != 32 {
		t.Errorf("MaxOpenConns default: got %d, want 32", cfg.ClickHouse.MaxOpenConns)
	}
	if cfg.ClickHouse.MaxIdleConns != 8 {
		t.Errorf("MaxIdleConns default: got %d, want 8", cfg.ClickHouse.MaxIdleConns)
	}
	if cfg.ClickHouse.MaxLifetime != time.Hour {
		t.Errorf("MaxLifetime default: got %v, want 1h", cfg.ClickHouse.MaxLifetime)
	}
	if cfg.ClickHouse.DialTimeout != 5*time.Second {
		t.Errorf("DialTimeout default: got %v, want 5s", cfg.ClickHouse.DialTimeout)
	}
}

func TestLoadOverridesFromEnv(t *testing.T) {
	setRequired(t)
	t.Setenv("HOST", "127.0.0.1")
	t.Setenv("PORT", "9123")
	t.Setenv("CLICKHOUSE_LOGS_CLUSTER_PORT", "8123")
	t.Setenv("CH_MAX_OPEN_CONNS", "64")
	t.Setenv("CH_MAX_IDLE_CONNS", "16")
	t.Setenv("CH_DIAL_TIMEOUT", "10s")

	cfg, err := Load()
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	checks := []struct {
		name string
		got  any
		want any
	}{
		{"Host", cfg.Host, "127.0.0.1"},
		{"Port", cfg.Port, "9123"},
		{"CH.Port", cfg.ClickHouse.Port, "8123"},
		{"CH.MaxOpenConns", cfg.ClickHouse.MaxOpenConns, 64},
		{"CH.MaxIdleConns", cfg.ClickHouse.MaxIdleConns, 16},
		{"CH.DialTimeout", cfg.ClickHouse.DialTimeout, 10 * time.Second},
	}
	for _, c := range checks {
		if c.got != c.want {
			t.Errorf("%s: got %v, want %v", c.name, c.got, c.want)
		}
	}
}

func TestLoadRejectsInvalidPoolConfig(t *testing.T) {
	setRequired(t)
	t.Setenv("CH_MAX_OPEN_CONNS", "0")
	if _, err := Load(); err == nil {
		t.Fatal("expected error when CH_MAX_OPEN_CONNS=0")
	}

	t.Setenv("CH_MAX_OPEN_CONNS", "8")
	t.Setenv("CH_MAX_IDLE_CONNS", "16")
	if _, err := Load(); err == nil {
		t.Fatal("expected error when CH_MAX_IDLE_CONNS > CH_MAX_OPEN_CONNS")
	}
}
