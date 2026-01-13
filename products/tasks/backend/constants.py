DEFAULT_TRUSTED_DOMAINS = [
    # PostHog Services
    "posthog.com",
    "us.posthog.com",
    "eu.posthog.com",
    # Version Control
    "github.com",
    "www.github.com",
    "api.github.com",
    "raw.githubusercontent.com",
    "objects.githubusercontent.com",
    "codeload.github.com",
    "avatars.githubusercontent.com",
    "camo.githubusercontent.com",
    "gist.github.com",
    "gitlab.com",
    "www.gitlab.com",
    "registry.gitlab.com",
    "bitbucket.org",
    "www.bitbucket.org",
    "api.bitbucket.org",
    # Container Registries
    "registry-1.docker.io",
    "auth.docker.io",
    "index.docker.io",
    "hub.docker.com",
    "www.docker.com",
    "production.cloudflare.docker.com",
    "download.docker.com",
    "*.gcr.io",
    "ghcr.io",
    "mcr.microsoft.com",
    "*.data.mcr.microsoft.com",
    # Cloud Platforms
    "cloud.google.com",
    "accounts.google.com",
    "gcloud.google.com",
    "*.googleapis.com",
    "storage.googleapis.com",
    "compute.googleapis.com",
    "container.googleapis.com",
    "azure.com",
    "portal.azure.com",
    "microsoft.com",
    "www.microsoft.com",
    "*.microsoftonline.com",
    "packages.microsoft.com",
    "dotnet.microsoft.com",
    "dot.net",
    "visualstudio.com",
    "dev.azure.com",
    "oracle.com",
    "www.oracle.com",
    "java.com",
    "www.java.com",
    "java.net",
    "www.java.net",
    "download.oracle.com",
    "yum.oracle.com",
    # Package Managers - JavaScript/Node
    "registry.npmjs.org",
    "www.npmjs.com",
    "www.npmjs.org",
    "npmjs.com",
    "npmjs.org",
    "yarnpkg.com",
    "registry.yarnpkg.com",
    # Package Managers - Python
    "pypi.org",
    "www.pypi.org",
    "files.pythonhosted.org",
    "pythonhosted.org",
    "test.pypi.org",
    "pypi.python.org",
    "pypa.io",
    "www.pypa.io",
    # Package Managers - Ruby
    "rubygems.org",
    "www.rubygems.org",
    "api.rubygems.org",
    "index.rubygems.org",
    "ruby-lang.org",
    "www.ruby-lang.org",
    "rubyforge.org",
    "www.rubyforge.org",
    "rubyonrails.org",
    "www.rubyonrails.org",
    "rvm.io",
    "get.rvm.io",
    # Package Managers - Rust
    "crates.io",
    "www.crates.io",
    "static.crates.io",
    "rustup.rs",
    "static.rust-lang.org",
    "www.rust-lang.org",
    # Package Managers - Go
    "proxy.golang.org",
    "sum.golang.org",
    "index.golang.org",
    "golang.org",
    "www.golang.org",
    "goproxy.io",
    "pkg.go.dev",
    # Package Managers - JVM
    "maven.org",
    "repo.maven.org",
    "central.maven.org",
    "repo1.maven.org",
    "jcenter.bintray.com",
    "gradle.org",
    "www.gradle.org",
    "services.gradle.org",
    "spring.io",
    "repo.spring.io",
    # Package Managers - Other Languages
    "packagist.org",
    "www.packagist.org",
    "repo.packagist.org",
    "nuget.org",
    "www.nuget.org",
    "api.nuget.org",
    "pub.dev",
    "api.pub.dev",
    "hex.pm",
    "www.hex.pm",
    "cpan.org",
    "www.cpan.org",
    "metacpan.org",
    "www.metacpan.org",
    "api.metacpan.org",
    "cocoapods.org",
    "www.cocoapods.org",
    "cdn.cocoapods.org",
    "haskell.org",
    "www.haskell.org",
    "hackage.haskell.org",
    "swift.org",
    "www.swift.org",
    # Linux Distributions
    "archive.ubuntu.com",
    "security.ubuntu.com",
    "ubuntu.com",
    "www.ubuntu.com",
    "*.ubuntu.com",
    "ppa.launchpad.net",
    "launchpad.net",
    "www.launchpad.net",
    # Development Tools & Platforms
    "dl.k8s.io",
    "pkgs.k8s.io",
    "k8s.io",
    "www.k8s.io",
    "releases.hashicorp.com",
    "apt.releases.hashicorp.com",
    "rpm.releases.hashicorp.com",
    "archive.releases.hashicorp.com",
    "hashicorp.com",
    "www.hashicorp.com",
    "repo.anaconda.com",
    "conda.anaconda.org",
    "anaconda.org",
    "www.anaconda.com",
    "anaconda.com",
    "continuum.io",
    "apache.org",
    "www.apache.org",
    "archive.apache.org",
    "downloads.apache.org",
    "eclipse.org",
    "www.eclipse.org",
    "download.eclipse.org",
    "nodejs.org",
    "www.nodejs.org",
    # Cloud Services & Monitoring
    "statsig.com",
    "www.statsig.com",
    "api.statsig.com",
    "*.sentry.io",
    # Content Delivery & Mirrors
    "*.sourceforge.net",
    "packagecloud.io",
    "*.packagecloud.io",
    # Schema & Configuration
    "json-schema.org",
    "www.json-schema.org",
    "json.schemastore.org",
    "www.schemastore.org",
]

SETUP_REPOSITORY_PROMPT = """
Your goal is to setup the repository in the current environment.

You are operating in a sandbox environment that is completely isolated and safe. You can execute any commands without risk - feel free to run builds, tests, install dependencies, or any other operations needed. You must install all dependencies necessary and setup the environment such that it is ready for executing code tasks.

CONTEXT:

CWD: {cwd}

REPOSITORY: {repository}

INSTRUCTIONS:

1. Install all dependencies necessary to run the repository
2. Run any setup scripts that are available
3. Verify the setup by running tests or build if available

DO NOT make any code changes to the repository. The final state of the disk of this sandbox is what will be used for subsequent tasks, so do not leave any cruft behind, and make sure the repository is in a ready to use state.

Rules:
- You should not ask the user for any input. This is run in a sandbox environment in a background process, so they will not be able to provide any input.
- The disk will be snapshooted immediately after you complete the task, and it will be reused for future tasks, so make sure everything you want is setup there.
- CRITICAL: You MUST NOT leave any uncommitted changes in the repository. The snapshot will be used to execute user tasks later, and we cannot modify their git history. Do not create any files that aren't already ignored by the repository's .gitignore, and do not add new entries to the .gitignore. If you accidentally create uncommitted files, you must delete them before completion. Check `git status` and ensure the working tree is clean at the end.
"""
