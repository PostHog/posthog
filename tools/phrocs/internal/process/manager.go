package process

import (
	"sync"

	tea "charm.land/bubbletea/v2"
	"github.com/posthog/posthog/phrocs/internal/config"
	"github.com/posthog/posthog/phrocs/internal/docker"
)

// Orchestrates all processes for the dev environment
type Manager struct {
	mu          sync.Mutex
	procs       []*Process
	byName      map[string]*Process
	send        func(tea.Msg)
	scrollback  int
	globalShell string
	quitCh      chan struct{}
	quitOnce    sync.Once
}

func NewManager(cfg *config.Config) *Manager {
	mgr := &Manager{
		scrollback:  cfg.Scrollback,
		globalShell: cfg.Shell,
		quitCh:      make(chan struct{}),
	}

	names := cfg.OrderedNames()
	mgr.procs = make([]*Process, 0, len(names))
	mgr.byName = make(map[string]*Process, len(names))

	for _, name := range names {
		pcfg := cfg.Procs[name]
		// Strip trailing "docker compose ... logs" from docker-compose shells
		if docker.IsDockerComposeShell(pcfg.Shell) {
			pcfg.Shell = docker.StripComposeLogsTail(pcfg.Shell)
		}
		proc := NewProcess(name, pcfg, cfg.Scrollback, cfg.Shell)
		mgr.procs = append(mgr.procs, proc)
		mgr.byName[name] = proc
	}

	return mgr
}

// UpdateDefaults updates the manager's default scrollback and global shell
// to match a new config, so that subsequent AddShell calls use the new values.
func (m *Manager) UpdateDefaults(cfg *config.Config) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.scrollback = cfg.Scrollback
	m.globalShell = cfg.Shell
}

// SetSend must be called before StartAll
func (m *Manager) SetSend(send func(tea.Msg)) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.send = send
}

// Launches all processes whose autostart is not explicitly false
func (m *Manager) StartAll() {
	m.mu.Lock()
	send := m.send
	procs := m.procs
	m.mu.Unlock()

	for _, p := range procs {
		if p.Cfg.ShouldAutostart() {
			_ = p.Start(send)
		}
	}
}

// Stops every running process in parallel and waits for all of them to exit
// (with SIGKILL escalation). Called on quit to ensure no orphaned processes
// keep ports occupied.
func (m *Manager) StopAll() {
	m.mu.Lock()
	procs := m.procs
	m.mu.Unlock()
	var wg sync.WaitGroup
	for _, p := range procs {
		wg.Add(1)
		go func() {
			defer wg.Done()
			p.Stop()
		}()
	}
	wg.Wait()
}

// Returns the ordered slice of all processes (safe for reading status/lines)
func (m *Manager) Procs() []*Process {
	m.mu.Lock()
	defer m.mu.Unlock()
	cp := make([]*Process, len(m.procs))
	copy(cp, m.procs)
	return cp
}

// Returns a process by name
func (m *Manager) Get(name string) (*Process, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()
	p, ok := m.byName[name]
	return p, ok
}

// Returns the send function so the TUI can pass it to Restart calls
func (m *Manager) Send() func(tea.Msg) {
	m.mu.Lock()
	defer m.mu.Unlock()
	return m.send
}

// Add creates a new process from config and appends it to the manager.
// If a process with the same name already exists, it is a no-op.
func (m *Manager) Add(name string, pcfg config.ProcConfig, scrollback int, globalShell string) *Process {
	m.mu.Lock()
	defer m.mu.Unlock()
	if _, ok := m.byName[name]; ok {
		return m.byName[name]
	}
	if docker.IsDockerComposeShell(pcfg.Shell) {
		pcfg.Shell = docker.StripComposeLogsTail(pcfg.Shell)
	}
	proc := NewProcess(name, pcfg, scrollback, globalShell)
	m.procs = append(m.procs, proc)
	m.byName[name] = proc
	return proc
}

// AddShell creates a new process from a shell command using the manager's
// default scrollback and global shell. If a process with the same name already
// exists, it is a no-op and the existing process is returned.
func (m *Manager) AddShell(name, shell string) *Process {
	return m.Add(name, config.ProcConfig{Shell: shell}, m.scrollback, m.globalShell)
}

// QuitCh returns a channel that is closed when Quit is invoked.
// Intended for the detached main loop to block on, then tear down cleanly.
func (m *Manager) QuitCh() <-chan struct{} {
	return m.quitCh
}

// Quit signals the manager to shut down. Idempotent; safe to call multiple times.
// Does not stop processes itself — the caller is responsible for calling StopAll
// after observing the quit signal, so teardown order stays in one place.
func (m *Manager) Quit() {
	m.quitOnce.Do(func() { close(m.quitCh) })
}

// Remove stops a process and removes it from the manager.
// Returns true if the process was found and removed.
func (m *Manager) Remove(name string) bool {
	m.mu.Lock()
	p, ok := m.byName[name]
	if !ok {
		m.mu.Unlock()
		return false
	}
	delete(m.byName, name)
	for i, proc := range m.procs {
		if proc.Name == name {
			m.procs = append(m.procs[:i], m.procs[i+1:]...)
			break
		}
	}
	m.mu.Unlock()
	p.Stop()
	return true
}
