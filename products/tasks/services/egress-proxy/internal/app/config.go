package app

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"net"
	"os"
	"strconv"
	"time"
)

type ServerConfig struct {
	ListenAddress          string `json:"listen_address"`
	AdminAddress           string `json:"admin_address"`
	RequestTimeoutSeconds  int    `json:"request_timeout_seconds"`
	ShutdownTimeoutSeconds int    `json:"shutdown_timeout_seconds"`
}

type ProxyConfig struct {
	ServerConfig
	CertificateFile          string         `json:"certificate_file"`
	PrivateKeyFile           string         `json:"private_key_file"`
	ClientCAFile             string         `json:"client_ca_file"`
	VerificationKeysFile     string         `json:"verification_keys_file"`
	RegistryURL              string         `json:"registry_url"`
	RegistryAllowClusterHTTP bool           `json:"registry_allow_cluster_http"`
	RegistryRegion           string         `json:"registry_region"`
	RegistrySigningKeyFile   string         `json:"registry_signing_key_file"`
	RegistryCAFile           string         `json:"registry_ca_file"`
	LookupTimeoutSeconds     int            `json:"lookup_timeout_seconds"`
	CacheEntries             int            `json:"cache_entries"`
	CacheLookups             int            `json:"cache_lookups"`
	AuditCapacity            int            `json:"audit_capacity"`
	GitRead                  *GitReadConfig `json:"git_read,omitempty"`
}

type GitReadConfig struct {
	GrantURL            string `json:"grant_url"`
	GrantSigningKeyFile string `json:"grant_signing_key_file"`
	GrantCAFile         string `json:"grant_ca_file"`
	SmokescreenURL      string `json:"smokescreen_url"`
	UpstreamCAFile      string `json:"upstream_ca_file"`
}

type RelayConfig struct {
	ServerConfig
	Endpoint        string `json:"endpoint"`
	CertificateFile string `json:"certificate_file"`
	PrivateKeyFile  string `json:"private_key_file"`
	ServerCAFile    string `json:"server_ca_file"`
	ClientCAFile    string `json:"client_ca_file"`
}

func readFile(path string) ([]byte, error) {
	f, err := os.Open(path)
	if err != nil {
		return nil, errors.New("configuration file unavailable")
	}
	defer f.Close()
	data, err := io.ReadAll(io.LimitReader(f, (1<<20)+1))
	if err != nil || len(data) > 1<<20 {
		return nil, errors.New("configuration file unreadable or too large")
	}
	return data, nil
}

func readConfig(path string, config any) error {
	data, err := readFile(path)
	if err != nil {
		return err
	}
	decoder := json.NewDecoder(bytes.NewReader(data))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(config); err != nil {
		return errors.New("invalid configuration JSON")
	}
	if decoder.Decode(new(any)) != io.EOF {
		return errors.New("unexpected configuration data")
	}
	return nil
}

func (c ServerConfig) validate() error {
	for _, address := range []string{c.ListenAddress, c.AdminAddress} {
		host, port, err := net.SplitHostPort(address)
		number, portErr := strconv.Atoi(port)
		if err != nil || portErr != nil || number < 0 || number > 65535 || (host != "" && net.ParseIP(host) == nil) {
			return errors.New("listeners require IP addresses and valid ports")
		}
	}
	host, _, _ := net.SplitHostPort(c.AdminAddress)
	if !net.ParseIP(host).IsLoopback() {
		return errors.New("administration must listen on loopback")
	}
	if c.RequestTimeoutSeconds <= 0 || c.RequestTimeoutSeconds > 3600 ||
		c.ShutdownTimeoutSeconds <= 0 || c.ShutdownTimeoutSeconds > 300 {
		return errors.New("invalid server timeouts")
	}
	return nil
}

func (c ServerConfig) requestTimeout() time.Duration {
	return time.Duration(c.RequestTimeoutSeconds) * time.Second
}

func LoadProxyConfig(path string) (ProxyConfig, error) {
	c := ProxyConfig{
		ServerConfig:         ServerConfig{ListenAddress: ":8443", AdminAddress: "127.0.0.1:9090", RequestTimeoutSeconds: 30, ShutdownTimeoutSeconds: 10},
		LookupTimeoutSeconds: 2, CacheEntries: 10000, CacheLookups: 64, AuditCapacity: 4096,
	}
	if err := readConfig(path, &c); err != nil {
		return c, err
	}
	if err := c.ServerConfig.validate(); err != nil {
		return c, err
	}
	if c.LookupTimeoutSeconds <= 0 || c.LookupTimeoutSeconds > c.RequestTimeoutSeconds ||
		c.CacheEntries <= 0 || c.CacheEntries > 1000000 || c.CacheLookups <= 0 || c.CacheLookups > 10000 ||
		c.AuditCapacity < 2 || c.AuditCapacity > 1000000 {
		return c, errors.New("invalid proxy limits")
	}
	return c, nil
}

func LoadRelayConfig(path string) (RelayConfig, error) {
	c := RelayConfig{ServerConfig: ServerConfig{
		ListenAddress: "127.0.0.1:8080", AdminAddress: "127.0.0.1:9090", RequestTimeoutSeconds: 300, ShutdownTimeoutSeconds: 10,
	}}
	if err := readConfig(path, &c); err != nil {
		return c, err
	}
	return c, c.ServerConfig.validate()
}
