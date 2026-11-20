package app

import (
	"context"
	"crypto/tls"
	"errors"
	"io"
	"log"
	"log/slog"
	"net"
	"net/http"
	"os"
	"sync/atomic"
	"time"

	"github.com/PostHog/posthog/products/tasks/services/egress-proxy/internal/telemetry"
)

func Run(ctx context.Context, mode, configPath string, reload <-chan os.Signal, output, diagnostics io.Writer) (runErr error) {
	logger := slog.New(slog.NewJSONHandler(diagnostics, nil))
	metrics := telemetry.NewMetrics()
	var config ServerConfig
	var handler http.Handler
	var tlsConfig *tls.Config
	var reloadConfig func() error
	var audit *telemetry.Audit
	ready := func() bool { return true }
	switch mode {
	case "proxy":
		settings, err := LoadProxyConfig(configPath)
		if err != nil {
			return err
		}
		config = settings.ServerConfig
		audit, err = telemetry.NewAudit(output, settings.AuditCapacity)
		if err != nil {
			return err
		}
		defer func() {
			drain, cancel := context.WithTimeout(context.Background(), time.Duration(config.ShutdownTimeoutSeconds)*time.Second)
			defer cancel()
			if audit.Close(drain) != nil {
				logger.Error("audit drain incomplete")
				runErr = errors.Join(runErr, errors.New("audit drain incomplete"))
			}
		}()
		metrics.BindAudit(audit)
		proxy, err := NewProxy(settings, audit, metrics)
		if err != nil {
			return err
		}
		defer proxy.Close()
		handler, tlsConfig, reloadConfig, ready = proxy, proxy.TLSConfig(), proxy.Reload, proxy.Ready
	case "relay":
		settings, err := LoadRelayConfig(configPath)
		if err != nil {
			return err
		}
		config = settings.ServerConfig
		relay, err := NewRelay(settings, metrics)
		if err != nil {
			return err
		}
		handler, ready = relay, relay.Ready
	default:
		return errors.New("unknown service mode")
	}
	live := func() bool { return audit == nil || !audit.Failed() }
	return serve(ctx, config, handler, tlsConfig, live, ready, reloadConfig, reload, metrics, logger)
}

func serve(ctx context.Context, config ServerConfig, handler http.Handler, tlsConfig *tls.Config,
	live, ready func() bool, reloadConfig func() error, reload <-chan os.Signal, metrics *telemetry.Metrics, logger *slog.Logger,
) error {
	listener, err := net.Listen("tcp", config.ListenAddress)
	if err != nil {
		return errors.New("request listener unavailable")
	}
	defer listener.Close()
	adminListener, err := net.Listen("tcp", config.AdminAddress)
	if err != nil {
		return errors.New("administration listener unavailable")
	}
	defer adminListener.Close()
	var draining atomic.Bool
	admin := http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet || r.URL.RawQuery != "" {
			w.WriteHeader(http.StatusNotFound)
			return
		}
		switch r.URL.Path {
		case "/livez":
			if !live() {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			w.WriteHeader(http.StatusNoContent)
		case "/readyz":
			if draining.Load() || !ready() {
				w.WriteHeader(http.StatusServiceUnavailable)
				return
			}
			w.WriteHeader(http.StatusNoContent)
		case "/metrics":
			metrics.Handler().ServeHTTP(w, r)
		default:
			w.WriteHeader(http.StatusNotFound)
		}
	})
	requests := &http.Server{
		Handler: handler, TLSConfig: tlsConfig, ReadHeaderTimeout: 5 * time.Second,
		IdleTimeout: 60 * time.Second, MaxHeaderBytes: 16 << 10, ErrorLog: log.New(io.Discard, "", 0),
	}
	administration := &http.Server{
		Handler: admin, ReadHeaderTimeout: 5 * time.Second, ReadTimeout: 10 * time.Second,
		WriteTimeout: 10 * time.Second, IdleTimeout: 30 * time.Second, MaxHeaderBytes: 16 << 10,
		ErrorLog: log.New(io.Discard, "", 0),
	}
	results := make(chan error, 2)
	go func() {
		if tlsConfig != nil {
			results <- requests.ServeTLS(listener, "", "")
		} else {
			results <- requests.Serve(listener)
		}
	}()
	go func() { results <- administration.Serve(adminListener) }()
	logger.Info("service started", "listen_address", listener.Addr().String(), "admin_address", adminListener.Addr().String())
	var serveErr error
loop:
	for {
		select {
		case <-ctx.Done():
			break loop
		case err := <-results:
			if !errors.Is(err, http.ErrServerClosed) {
				serveErr = errors.New("HTTP server stopped unexpectedly")
			}
			break loop
		case _, ok := <-reload:
			if !ok {
				reload = nil
				continue
			}
			if reloadConfig == nil {
				logger.Warn("relay credential changes require restart")
				continue
			}
			if err := reloadConfig(); err != nil {
				metrics.Reload("failure")
				logger.Error("configuration reload failed; retaining active configuration", "error", err)
			} else {
				metrics.Reload("success")
				logger.Info("configuration reloaded")
			}
		}
	}
	draining.Store(true)
	shutdown, cancel := context.WithTimeout(context.Background(), time.Duration(config.ShutdownTimeoutSeconds)*time.Second)
	defer cancel()
	if requests.Shutdown(shutdown) != nil {
		requests.Close()
		serveErr = errors.New("request drain incomplete")
	}
	if administration.Shutdown(shutdown) != nil {
		administration.Close()
	}
	logger.Info("service stopped")
	return serveErr
}
