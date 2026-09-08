package pkgs

import devshell "github.com/tonky/enve/schema/v1:schema"

// -------------------------------------------------------------
// Core Developer Utilities & CLI Tools
// -------------------------------------------------------------

ripgrep: devshell.#RustBuildSpec & {
	pname:   "ripgrep"
	version: "15.2.0"
	src:     "https://github.com/BurntSushi/ripgrep/archive/refs/tags/15.2.0.tar.gz"
}

bat: devshell.#RustBuildSpec & {
	pname:   "bat"
	version: "0.26.1"
	src:     "https://github.com/sharkdp/bat/archive/refs/tags/v0.26.1.tar.gz"
}

eza: devshell.#RustBuildSpec & {
	pname:   "eza"
	version: "0.23.5"
	src:     "https://github.com/eza-community/eza/archive/refs/tags/v0.23.5.tar.gz"
}

just: devshell.#RustBuildSpec & {
	pname:   "just"
	version: "1.58.0"
	src:     "https://github.com/casey/just/archive/refs/tags/1.58.0.tar.gz"
}

fzf: devshell.#GoBuildSpec & {
	pname:       "fzf"
	version:     "0.60.3"
	src:         "https://github.com/junegunn/fzf/archive/refs/tags/v0.60.3.tar.gz"
	subPackages: "."
}

jq: devshell.#RustBuildSpec & {
	pname:   "jq"
	version: "1.7.1"
	src:     "https://github.com/jqlang/jq/archive/refs/tags/jq-1.7.1.tar.gz"
}

fd: devshell.#RustBuildSpec & {
	pname:   "fd"
	version: "10.2.0"
	src:     "https://github.com/sharkdp/fd/archive/refs/tags/v10.2.0.tar.gz"
}

lazygit: devshell.#GoBuildSpec & {
	pname:       "lazygit"
	version:     "0.64.0"
	src:         "https://github.com/jesseduffield/lazygit/archive/refs/tags/v0.64.0.tar.gz"
	subPackages: "."
	ldflags: ["-X main.version=0.64.0"]
}

gh: devshell.#GoBuildSpec & {
	pname:       "gh"
	version:     "2.97.0"
	src:         "https://github.com/cli/cli/archive/refs/tags/v2.97.0.tar.gz"
	subPackages: "cmd/gh"
}

git: devshell.#RustBuildSpec & {
	pname:   "git"
	version: "2.48.1"
	src:     "https://github.com/git/git/archive/refs/tags/v2.48.1.tar.gz"
}

curl: devshell.#RustBuildSpec & {
	pname:   "curl"
	version: "8.12.1"
	src:     "https://github.com/curl/curl/archive/refs/tags/curl-8_12_1.tar.gz"
}

wget: devshell.#RustBuildSpec & {
	pname:   "wget"
	version: "1.25.0"
	src:     "https://ftp.gnu.org/gnu/wget/wget-1.25.0.tar.gz"
}

tmux: devshell.#RustBuildSpec & {
	pname:   "tmux"
	version: "3.5a"
	src:     "https://github.com/tmux/tmux/releases/download/3.5a/tmux-3.5a.tar.gz"
}

zoxide: devshell.#RustBuildSpec & {
	pname:   "zoxide"
	version: "0.9.6"
	src:     "https://github.com/ajeetdsouza/zoxide/archive/refs/tags/v0.9.6.tar.gz"
}

delta: devshell.#RustBuildSpec & {
	pname:   "delta"
	version: "0.18.2"
	src:     "https://github.com/dandavison/delta/archive/refs/tags/0.18.2.tar.gz"
}

watchexec: devshell.#RustBuildSpec & {
	pname:   "watchexec"
	version: "2.5.1"
	src:     "https://github.com/watchexec/watchexec/archive/refs/tags/v2.5.1.tar.gz"
}

typescript: devshell.#NodeBuildSpec & {
	pname:   "typescript"
	version: "5.9.3"
	src:     "https://github.com/microsoft/TypeScript/archive/refs/tags/v5.9.3.tar.gz"
}

wasm_pack: devshell.#RustBuildSpec & {
	pname:   "wasm-pack"
	version: "0.15.0"
	src:     "https://github.com/rustwasm/wasm-pack/archive/refs/tags/v0.15.0.tar.gz"
}

binaryen: devshell.#RustBuildSpec & {
	pname:   "binaryen"
	version: "132"
	src:     "https://github.com/WebAssembly/binaryen/archive/refs/tags/version_132.tar.gz"
}

wasm_bindgen_cli: devshell.#RustBuildSpec & {
	pname:   "wasm-bindgen-cli"
	version: "0.2.127"
	src:     "https://github.com/rustwasm/wasm-bindgen/archive/refs/tags/0.2.127.tar.gz"
}

clang: devshell.#BuildSpec & {
	pname:   "clang"
	version: "21.1.8"
	src:     "https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.8/clang-21.1.8.src.tar.xz"
}

gcc: devshell.#BuildSpec & {
	pname:   "gcc"
	version: "14.2.0"
	src:     "https://ftp.gnu.org/gnu/gcc/gcc-14.2.0/gcc-14.2.0.tar.xz"
}

llvm: devshell.#BuildSpec & {
	pname:   "llvm"
	version: "21.1.8"
	src:     "https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.8/llvm-21.1.8.src.tar.xz"
}

lld: devshell.#BuildSpec & {
	pname:   "lld"
	version: "21.1.8"
	src:     "https://github.com/llvm/llvm-project/releases/download/llvmorg-21.1.8/lld-21.1.8.src.tar.xz"
}

mold: devshell.#BuildSpec & {
	pname:   "mold"
	version: "2.42.0"
	src:     "https://github.com/rui314/mold/archive/refs/tags/v2.42.0.tar.gz"
}

binutils: devshell.#BuildSpec & {
	pname:   "binutils"
	version: "2.44"
	src:     "https://ftp.gnu.org/gnu/binutils/binutils-2.44.tar.xz"
}

bintools: binutils

gnumake: devshell.#BuildSpec & {
	pname:   "gnumake"
	version: "4.4.1"
	src:     "https://ftp.gnu.org/gnu/make/make-4.4.1.tar.gz"
}

make: gnumake

procps: devshell.#BuildSpec & {
	pname:   "procps"
	version: "4.0.4"
	src:     "https://gitlab.com/procps-ng/procps/-/archive/v4.0.4/procps-v4.0.4.tar.gz"
}

python3: devshell.#RustBuildSpec & {
	pname:   "python3"
	version: "3.12.0"
	src:     "https://www.python.org/ftp/python/3.12.0/Python-3.12.0.tar.xz"
}

python: python3
python312: python3
python313: python3
python311: devshell.#RustBuildSpec & {
	pname:   "python3"
	version: "3.11.10"
	src:     "https://www.python.org/ftp/python/3.11.10/Python-3.11.10.tar.xz"
}
python310: devshell.#RustBuildSpec & {
	pname:   "python3"
	version: "3.10.15"
	src:     "https://www.python.org/ftp/python/3.10.15/Python-3.10.15.tar.xz"
}

uv: devshell.#RustBuildSpec & {
	pname:   "uv"
	version: "0.6.3"
	src:     "https://github.com/astral-sh/uv/archive/refs/tags/0.6.3.tar.gz"
}

pnpm: devshell.#NodeBuildSpec & {
	pname:       "pnpm"
	version:     "10.5.2"
	src:         "https://registry.npmjs.org/pnpm/-/pnpm-10.5.2.tgz"
	nodeVersion: "20.x"
}

tesseract: devshell.#RustBuildSpec & {
	pname:   "tesseract"
	version: "5.5.0"
	src:     "https://github.com/tesseract-ocr/tesseract/archive/refs/tags/5.5.0.tar.gz"
}

ghostscript: devshell.#RustBuildSpec & {
	pname:   "ghostscript"
	version: "10.04.0"
	src:     "https://github.com/ArtifexSoftware/ghostpdl-downloads/releases/download/gs10040/ghostscript-10.04.0.tar.gz"
}

poppler: devshell.#RustBuildSpec & {
	pname:   "poppler"
	version: "25.02.0"
	src:     "https://poppler.freedesktop.org/poppler-25.02.0.tar.xz"
}

unpaper: devshell.#RustBuildSpec & {
	pname:   "unpaper"
	version: "7.0.0"
	src:     "https://github.com/unpaper/unpaper/archive/refs/tags/unpaper-7.0.0.tar.gz"
}

qpdf: devshell.#RustBuildSpec & {
	pname:   "qpdf"
	version: "11.10.1"
	src:     "https://github.com/qpdf/qpdf/archive/refs/tags/v11.10.1.tar.gz"
}

file: devshell.#RustBuildSpec & {
	pname:   "file"
	version: "5.45"
	src:     "https://astron.com/pub/file/file-5.45.tar.gz"
}

imagemagick: devshell.#RustBuildSpec & {
	pname:   "imagemagick"
	version: "7.1.1"
	src:     "https://github.com/ImageMagick/ImageMagick/archive/refs/tags/7.1.1-43.tar.gz"
}

yarn: devshell.#NodeBuildSpec & {
	pname:       "yarn"
	version:     "1.22.22"
	src:         "https://registry.npmjs.org/yarn/-/yarn-1.22.22.tgz"
	nodeVersion: "20.x"
}

gitleaks: devshell.#GoBuildSpec & {
	pname:       "gitleaks"
	version:     "8.24.3"
	src:         "https://github.com/gitleaks/gitleaks/archive/refs/tags/v8.24.3.tar.gz"
	subPackages: "."
}

graphicsmagick: devshell.#RustBuildSpec & {
	pname:   "graphicsmagick"
	version: "1.3.45"
	src:     "https://sourceforge.net/projects/graphicsmagick/files/graphicsmagick/1.3.45/GraphicsMagick-1.3.45.tar.xz"
}

exiftool: devshell.#RustBuildSpec & {
	pname:   "exiftool"
	version: "13.23"
	src:     "https://exiftool.org/Image-ExifTool-13.23.tar.gz"
}

bundler: devshell.#RustBuildSpec & {
	pname:   "bundler"
	version: "2.6.5"
	src:     "https://rubygems.org/downloads/bundler-2.6.5.gem"
}

libyaml: devshell.#RustBuildSpec & {
	pname:   "libyaml"
	version: "0.2.5"
	src:     "https://github.com/yaml/libyaml/archive/refs/tags/0.2.5.tar.gz"
}

krb5: devshell.#RustBuildSpec & {
	pname:   "krb5"
	version: "1.21.3"
	src:     "https://kerberos.org/dist/krb5/1.21/krb5-1.21.3.tar.gz"
}

icu: devshell.#RustBuildSpec & {
	pname:   "icu"
	version: "74.2"
	src:     "https://github.com/unicode-org/icu/releases/download/release-74-2/icu4c-74_2-src.tgz"
}

re2: devshell.#RustBuildSpec & {
	pname:   "re2"
	version: "2024-07-02"
	src:     "https://github.com/google/re2/archive/refs/tags/2024-07-02.tar.gz"
}

zlib: devshell.#RustBuildSpec & {
	pname:   "zlib"
	version: "1.3.1"
	src:     "https://zlib.net/zlib-1.3.1.tar.gz"
}

openssl: devshell.#RustBuildSpec & {
	pname:   "openssl"
	version: "3.4.1"
	src:     "https://www.openssl.org/source/openssl-3.4.1.tar.gz"
}

libxml2: devshell.#RustBuildSpec & {
	pname:   "libxml2"
	version: "2.13.5"
	src:     "https://download.gnome.org/sources/libxml2/2.13/libxml2-2.13.5.tar.xz"
}

libxslt: devshell.#RustBuildSpec & {
	pname:   "libxslt"
	version: "1.1.42"
	src:     "https://download.gnome.org/sources/libxslt/1.1/libxslt-1.1.42.tar.xz"
}

pkg_config: devshell.#RustBuildSpec & {
	pname:   "pkg-config"
	version: "0.29.2"
	src:     "https://pkgconfig.freedesktop.org/releases/pkg-config-0.29.2.tar.gz"
}

gcc_lib: devshell.#RustBuildSpec & {
	pname:   "gcc-lib"
	version: "15.2.0"
	src:     "https://ftp.gnu.org/gnu/gcc/gcc-15.2.0/gcc-15.2.0.tar.xz"
}

gitaly: devshell.#GoBuildSpec & {
	pname:   "gitaly"
	version: "19.3.1"
	src:     "https://gitlab.com/gitlab-org/gitaly"
}

praefect: devshell.#GoBuildSpec & {
	pname:   "praefect"
	version: "19.3.1"
	src:     "https://gitlab.com/gitlab-org/gitaly"
}

meson: devshell.#RustBuildSpec & {
	pname:   "meson"
	version: "1.6.1"
	src:     "https://github.com/mesonbuild/meson"
}

ninja: devshell.#RustBuildSpec & {
	pname:   "ninja"
	version: "1.12.1"
	src:     "https://github.com/ninja-build/ninja"
}

// -------------------------------------------------------------
// Rust Toolchain Companions
// -------------------------------------------------------------

rustfmt: devshell.#BuildSpec & {
	pname:   "rustfmt"
	version: "1.98.0"
	src:     "https://github.com/rust-lang/rustfmt/archive/refs/tags/v1.98.0.tar.gz"
}

cargo_watch: devshell.#RustBuildSpec & {
	pname:   "cargo-watch"
	version: "8.5.3"
	src:     "https://github.com/watchexec/cargo-watch/archive/refs/tags/v8.5.3.tar.gz"
}

cargo_nextest: devshell.#RustBuildSpec & {
	pname:   "cargo-nextest"
	version: "0.9.89"
	src:     "https://github.com/nextest-rs/nextest/archive/refs/tags/cargo-nextest-0.9.89.tar.gz"
}

// -------------------------------------------------------------
// Cloud Native & Kubernetes Tools
// -------------------------------------------------------------

kubectl: devshell.#GoBuildSpec & {
	pname:       "kubectl"
	version:     "1.31.2"
	src:         "https://github.com/kubernetes/kubectl/archive/refs/tags/v1.31.2.tar.gz"
	subPackages: "cmd/kubectl"
}

k9s: devshell.#GoBuildSpec & {
	pname:       "k9s"
	version:     "0.32.7"
	src:         "https://github.com/derailed/k9s/archive/refs/tags/v0.32.7.tar.gz"
	subPackages: "."
}

helm: devshell.#GoBuildSpec & {
	pname:       "helm"
	version:     "3.16.3"
	src:         "https://github.com/helm/helm/archive/refs/tags/v3.16.3.tar.gz"
	subPackages: "cmd/helm"
}

kustomize: devshell.#GoBuildSpec & {
	pname:       "kustomize"
	version:     "5.5.0"
	src:         "https://github.com/kubernetes-sigs/kustomize/archive/refs/tags/kustomize/v5.5.0.tar.gz"
	subPackages: "cmd/kustomize"
}

stern: devshell.#GoBuildSpec & {
	pname:       "stern"
	version:     "1.31.0"
	src:         "https://github.com/stern/stern/archive/refs/tags/v1.31.0.tar.gz"
	subPackages: "."
}

kubectx: devshell.#GoBuildSpec & {
	pname:       "kubectx"
	version:     "0.9.5"
	src:         "https://github.com/ahmetb/kubectx/archive/refs/tags/v0.9.5.tar.gz"
	subPackages: "cmd/kubectx"
}

opentofu: devshell.#GoBuildSpec & {
	pname:       "opentofu"
	version:     "1.8.6"
	src:         "https://github.com/opentofu/opentofu/archive/refs/tags/v1.8.6.tar.gz"
	subPackages: "cmd/tofu"
}

kind: devshell.#GoBuildSpec & {
	pname:       "kind"
	version:     "0.25.0"
	src:         "https://github.com/kubernetes-sigs/kind/archive/refs/tags/v0.25.0.tar.gz"
	subPackages: "."
}

minikube: devshell.#GoBuildSpec & {
	pname:       "minikube"
	version:     "1.34.0"
	src:         "https://github.com/kubernetes/minikube/archive/refs/tags/v1.34.0.tar.gz"
	subPackages: "cmd/minikube"
}

yq: devshell.#GoBuildSpec & {
	pname:       "yq"
	version:     "4.44.6"
	src:         "https://github.com/mikefarah/yq/archive/refs/tags/v4.44.6.tar.gz"
	subPackages: "."
}

