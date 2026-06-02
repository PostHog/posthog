// posthog-tool-runner is a customer-deployed process that exposes
// in-network tools (Grafana, k8s, internal MCPs, shell commands) to
// PostHog-hosted agents via an outbound-only HTTPS protocol.
//
// See docs/agent-platform/plans/self-hosted-tool-runners.md for the design.
package main

import (
	"context"
	"errors"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"strings"
	"sync"
	"syscall"

	"github.com/posthog/posthog/services/agent-tool-runner/client"
	"github.com/posthog/posthog/services/agent-tool-runner/config"
	"github.com/posthog/posthog/services/agent-tool-runner/runner"
	"github.com/posthog/posthog/services/agent-tool-runner/sources"
)

// Version is overridden at build time via -ldflags. Surfaced in heartbeats.
var Version = "dev"

// projectRunner pairs each config.ProjectConfig with its constructed
// runner.Runner. Used by main.run and the health server.
type projectRunner struct {
	project config.ProjectConfig
	runner  *runner.Runner
}

func main() {
	configPath := flag.String("config", "/etc/posthog-tool-runner/config.yaml", "Path to the runner YAML config")
	// :18081 avoids a default-port collision with OrbStack/Docker
	// Desktop, which both grab :8080 on macOS. Kubernetes deployments
	// should override this anyway.
	healthAddr := flag.String("health-addr", ":18081", "Address for the /healthz HTTP endpoint")
	flag.Parse()

	logger := slog.New(slog.NewJSONHandler(os.Stderr, &slog.HandlerOptions{Level: slog.LevelInfo}))
	slog.SetDefault(logger)

	if err := run(*configPath, *healthAddr, logger); err != nil {
		logger.Error("runner exited with error", slog.String("err", err.Error()))
		os.Exit(1)
	}
}

func run(configPath, healthAddr string, logger *slog.Logger) error {
	cfg, err := config.Load(configPath)
	if err != nil {
		return err
	}

	// SIGINT / SIGTERM cancel the root context, draining everything.
	ctx, cancel := signal.NotifyContext(context.Background(), syscall.SIGINT, syscall.SIGTERM)
	defer cancel()

	// Build tool sources once — they're shared across every project loop.
	// MCP sources open their upstream connections during this call; if any
	// fail we abort early rather than starting project loops with a
	// half-wired catalog. (PostHog-side unreachability is NOT a build-time
	// failure — the runner loop retries indefinitely once it starts.)
	sourceByName, err := buildSources(ctx, cfg.ToolSources, logger)
	if err != nil {
		return err
	}
	defer closeSources(sourceByName, logger)

	// Build all runners up front so the health server has every State()
	// reference from the moment it starts serving requests.
	prs := make([]projectRunner, 0, len(cfg.Projects))
	for _, project := range cfg.Projects {
		r, err := buildRunner(project, sourceByName, logger)
		if err != nil {
			return fmt.Errorf("project %d (slug=%s): %w", project.ProjectID, project.Slug, err)
		}
		prs = append(prs, projectRunner{project: project, runner: r})
	}

	// Health server runs alongside the project loops. It surfaces each
	// runner's state — "healthy" only when every project is `live`.
	healthDone := startHealthServer(ctx, healthAddr, prs, logger)

	var wg sync.WaitGroup
	errCh := make(chan error, len(prs))

	for _, pr := range prs {
		wg.Add(1)
		go func(pr projectRunner) {
			defer wg.Done()
			projectLogger := logger.With(
				slog.Int("project_id", pr.project.ProjectID),
				slog.String("slug", pr.project.Slug),
				slog.String("endpoint", pr.project.Endpoint),
			)
			projectLogger.Info("starting project loop")
			if err := pr.runner.Run(ctx); err != nil && !errors.Is(err, context.Canceled) {
				errCh <- fmt.Errorf("project %d (slug=%s): %w", pr.project.ProjectID, pr.project.Slug, err)
			}
			projectLogger.Info("project loop stopped")
		}(pr)
	}

	wg.Wait()
	close(errCh)
	<-healthDone

	// Aggregate non-cancellation errors. One project's failure does not
	// take the runner down — we surface the first error after every loop
	// has exited so the operator can decide.
	var firstErr error
	for err := range errCh {
		if firstErr == nil {
			firstErr = err
		}
		logger.Warn("project loop terminated with error", slog.String("err", err.Error()))
	}
	return firstErr
}

// buildSources turns the YAML tool_sources list into a name -> Source map.
// Returned sources are shared across every project loop that exposes them.
// MCP sources are connected to their upstream during this call so the
// catalog cache is primed before any project loop starts heartbeating.
func buildSources(ctx context.Context, specs []config.ToolSourceConfig, logger *slog.Logger) (map[string]runner.Source, error) {
	out := make(map[string]runner.Source, len(specs))
	commandSpecsByName := make(map[string][]sources.CommandSpec)

	for _, spec := range specs {
		switch spec.Source {
		case "mcp":
			src, err := sources.NewMCPSource(spec.Name, spec.Endpoint)
			if err != nil {
				closeSources(out, logger)
				return nil, fmt.Errorf("tool source %q: %w", spec.Name, err)
			}
			if err := src.Connect(ctx); err != nil {
				closeSources(out, logger)
				return nil, fmt.Errorf("tool source %q: %w", spec.Name, err)
			}
			out[spec.Name] = src
			logger.Info("connected to upstream MCP",
				slog.String("source", spec.Name),
				slog.String("endpoint", spec.Endpoint),
				slog.Int("tools", len(src.Tools())))

		case "command":
			// A `command` source maps to one tool entry. We accumulate
			// them and build a single CommandSource per source name so
			// authors can colocate related shell commands under one name.
			commandSpecsByName[spec.Name] = append(commandSpecsByName[spec.Name], sources.CommandSpec{
				Name:        spec.Name,
				Description: spec.Description,
				ArgsSchema:  spec.ArgsSchema,
				Command:     spec.Command,
			})

		default:
			closeSources(out, logger)
			return nil, fmt.Errorf("tool source %q: unknown source kind %q", spec.Name, spec.Source)
		}
	}

	for name, specs := range commandSpecsByName {
		src, err := sources.NewCommandSource(specs)
		if err != nil {
			closeSources(out, logger)
			return nil, fmt.Errorf("tool source %q: %w", name, err)
		}
		out[name] = src
	}
	return out, nil
}

// closeSources releases every Source's resources. Errors are logged, not
// returned — shutdown is best-effort, and we don't want a stuck close to
// mask the original failure.
func closeSources(sourcesByName map[string]runner.Source, logger *slog.Logger) {
	for name, src := range sourcesByName {
		if err := src.Close(); err != nil {
			logger.Warn("close source failed",
				slog.String("source", name),
				slog.String("err", err.Error()))
		}
	}
}

// buildRunner constructs one project loop. Selects the sources this project
// references via its `expose:` list.
func buildRunner(project config.ProjectConfig, sourceByName map[string]runner.Source, logger *slog.Logger) (*runner.Runner, error) {
	token, err := readTokenFile(project.TokenSecretRef)
	if err != nil {
		return nil, err
	}

	httpClient, err := client.New(client.Options{
		Endpoint: project.Endpoint,
		Token:    token,
	})
	if err != nil {
		return nil, err
	}

	// Collect the unique sources this project references. A project may
	// expose multiple tools from the same source; we want each source
	// instance in `Sources` exactly once. An expose entry resolves to a
	// source via either exact-match (command sources whose name embeds
	// the dot, like `kubernetes.restart_deployment`) or prefix-match
	// (MCP sources contributing many tools under their `<name>.` prefix).
	seenSources := make(map[runner.Source]struct{}, len(project.Expose))
	projectSources := make([]runner.Source, 0, len(project.Expose))
	for _, exposed := range project.Expose {
		source, ok := sourceByName[exposed]
		if !ok {
			sourceName, _, qualOk := splitQualifiedName(exposed)
			if !qualOk {
				return nil, fmt.Errorf("expose %q: must be in `<source>.<tool>` form", exposed)
			}
			source, ok = sourceByName[sourceName]
			if !ok {
				return nil, fmt.Errorf("expose %q: no tool source defined", exposed)
			}
		}
		if _, dup := seenSources[source]; dup {
			continue
		}
		seenSources[source] = struct{}{}
		projectSources = append(projectSources, source)
	}

	return runner.New(runner.Options{
		Version: Version,
		Sources: projectSources,
		Expose:  project.Expose,
		Client:  httpClient,
		Logger: logger.With(
			slog.Int("project_id", project.ProjectID),
			slog.String("slug", project.Slug),
		),
	})
}

func readTokenFile(path string) (string, error) {
	bytes, err := os.ReadFile(path)
	if err != nil {
		return "", fmt.Errorf("read token at %s: %w", path, err)
	}
	token := strings.TrimSpace(string(bytes))
	if token == "" {
		return "", fmt.Errorf("token file %s is empty", path)
	}
	return token, nil
}

// splitQualifiedName mirrors the helper in config.go (kept local to avoid
// exporting an internal helper). Splits on the first dot.
func splitQualifiedName(qualified string) (source, tool string, ok bool) {
	if i := strings.IndexByte(qualified, '.'); i > 0 && i < len(qualified)-1 {
		return qualified[:i], qualified[i+1:], true
	}
	return "", "", false
}
