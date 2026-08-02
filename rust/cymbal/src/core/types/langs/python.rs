use std::sync::LazyLock;

use common_types::error_tracking::FrameId;
use regex::Regex;
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha512};

use crate::{
    frames::{Context, ContextLine, Frame},
    langs::CommonFrameMetadata,
};

// Installed third-party packages, e.g. ".../site-packages/redis/connection.py"
static EXTERNAL_PACKAGE_PATH: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[/\\](?:dist|site)-packages[/\\]").unwrap());

// Stdlib install layout, e.g. "/usr/local/lib/python3.11/socket.py"
static STDLIB_PATH: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"[/\\][Ll]ib[/\\]python\d+(?:\.\d+)?[/\\]").unwrap());

// Top-level public stdlib module names (union across Python 3.x versions), for
// frames that arrive without a usable abs_path.
const STDLIB_MODULES: &[&str] = &[
    "abc",
    "aifc",
    "argparse",
    "array",
    "ast",
    "asyncio",
    "atexit",
    "audioop",
    "base64",
    "bdb",
    "binascii",
    "bisect",
    "builtins",
    "bz2",
    "cProfile",
    "calendar",
    "cgi",
    "cgitb",
    "chunk",
    "cmath",
    "cmd",
    "code",
    "codecs",
    "codeop",
    "collections",
    "colorsys",
    "compileall",
    "concurrent",
    "configparser",
    "contextlib",
    "contextvars",
    "copy",
    "copyreg",
    "crypt",
    "csv",
    "ctypes",
    "curses",
    "dataclasses",
    "datetime",
    "dbm",
    "decimal",
    "difflib",
    "dis",
    "doctest",
    "email",
    "encodings",
    "ensurepip",
    "enum",
    "errno",
    "faulthandler",
    "fcntl",
    "filecmp",
    "fileinput",
    "fnmatch",
    "fractions",
    "ftplib",
    "functools",
    "gc",
    "getopt",
    "getpass",
    "gettext",
    "glob",
    "graphlib",
    "grp",
    "gzip",
    "hashlib",
    "heapq",
    "hmac",
    "html",
    "http",
    "imaplib",
    "imghdr",
    "importlib",
    "inspect",
    "io",
    "ipaddress",
    "itertools",
    "json",
    "keyword",
    "linecache",
    "locale",
    "logging",
    "lzma",
    "mailbox",
    "mailcap",
    "marshal",
    "math",
    "mimetypes",
    "mmap",
    "modulefinder",
    "msvcrt",
    "multiprocessing",
    "netrc",
    "nntplib",
    "ntpath",
    "numbers",
    "opcode",
    "operator",
    "optparse",
    "os",
    "pathlib",
    "pdb",
    "pickle",
    "pickletools",
    "pipes",
    "pkgutil",
    "platform",
    "plistlib",
    "poplib",
    "posix",
    "posixpath",
    "pprint",
    "profile",
    "pstats",
    "pty",
    "pwd",
    "py_compile",
    "pyclbr",
    "pydoc",
    "queue",
    "quopri",
    "random",
    "re",
    "readline",
    "reprlib",
    "resource",
    "rlcompleter",
    "runpy",
    "sched",
    "secrets",
    "select",
    "selectors",
    "shelve",
    "shlex",
    "shutil",
    "signal",
    "site",
    "smtplib",
    "sndhdr",
    "socket",
    "socketserver",
    "sqlite3",
    "ssl",
    "stat",
    "statistics",
    "string",
    "stringprep",
    "struct",
    "subprocess",
    "sunau",
    "symtable",
    "sys",
    "sysconfig",
    "syslog",
    "tabnanny",
    "tarfile",
    "telnetlib",
    "tempfile",
    "termios",
    "textwrap",
    "threading",
    "time",
    "timeit",
    "tkinter",
    "token",
    "tokenize",
    "tomllib",
    "trace",
    "traceback",
    "tracemalloc",
    "tty",
    "turtle",
    "types",
    "typing",
    "unicodedata",
    "unittest",
    "urllib",
    "uu",
    "uuid",
    "venv",
    "warnings",
    "wave",
    "weakref",
    "webbrowser",
    "winreg",
    "winsound",
    "wsgiref",
    "xdrlib",
    "xml",
    "xmlrpc",
    "zipapp",
    "zipfile",
    "zipimport",
    "zlib",
    "zoneinfo",
];

#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct RawPythonFrame {
    #[serde(rename = "abs_path")]
    pub path: Option<String>, // Absolute path to the file - used for in_app detection
    pub context_line: Option<String>, // The line of code the exception came from
    pub filename: String,             // The relative path of the file the context line is in
    pub function: String,             // The name of the function the exception came from
    pub lineno: Option<u32>,          // The line number of the context line
    pub module: Option<String>,       // The python-import style module name the function is in
    #[serde(default)]
    pub pre_context: Vec<String>, // The lines of code before the context line
    #[serde(default)]
    pub post_context: Vec<String>, // The lines of code after the context line
    pub code_variables: Option<serde_json::Value>,
    #[serde(flatten)]
    pub meta: CommonFrameMetadata,
}

impl RawPythonFrame {
    pub fn frame_id(&self) -> String {
        // We don't have version info for python frames, so we rely on
        // the module, function, line number and surrounding context to
        // uniquely identify a frame, with the intuition being that even
        // if two frames are from two different library versions, if the
        // files they're in are sufficiently similar we can consider
        // them to be the same frame
        let mut hasher = Sha512::new();
        self.context_line
            .as_ref()
            .inspect(|c| hasher.update(c.as_bytes()));
        hasher.update(self.filename.as_bytes());
        hasher.update(self.function.as_bytes());
        hasher.update(self.lineno.unwrap_or_default().to_be_bytes());
        self.module
            .as_ref()
            .inspect(|m| hasher.update(m.as_bytes()));
        self.pre_context
            .iter()
            .chain(self.post_context.iter())
            .for_each(|line| {
                hasher.update(line.as_bytes());
            });
        format!("{:x}", hasher.finalize())
    }

    // Clients compute in_app from their local filesystem layout (and default to
    // true when unsure), so identical stacks arrive with different in_app masks
    // depending on the host they were captured on. Fingerprinting selects frames
    // by in_app, so each mask would mint a new fingerprint for the same crash.
    // Demote frames that are clearly stdlib or installed-package code; we never
    // promote, so explicit client config (in_app_exclude) still wins.
    pub fn in_app(&self) -> bool {
        self.meta.in_app && !self.is_library_code()
    }

    fn is_library_code(&self) -> bool {
        if self.has_stdlib_pseudo_filename() {
            return true;
        }
        if let Some(path) = &self.path {
            if EXTERNAL_PACKAGE_PATH.is_match(path) || STDLIB_PATH.is_match(path) {
                return true;
            }
            return false;
        }
        if EXTERNAL_PACKAGE_PATH.is_match(&self.filename) {
            return true;
        }
        self.module
            .as_deref()
            .and_then(|module| module.split('.').next())
            .is_some_and(|top_level| STDLIB_MODULES.contains(&top_level))
    }

    fn has_stdlib_pseudo_filename(&self) -> bool {
        self.module
            .as_deref()
            .and_then(|module| module.split('.').next())
            .is_some_and(|top_level| STDLIB_MODULES.contains(&top_level))
            && (is_python_pseudo_filename(&self.filename)
                || self
                    .path
                    .as_deref()
                    .is_some_and(contains_python_pseudo_filename))
    }

    pub fn get_context(&self) -> Option<Context> {
        let context_line = self.context_line.as_ref()?;
        let lineno = self.lineno?;

        let line = ContextLine::new(lineno, context_line);

        let before = self
            .pre_context
            .iter()
            .rev()
            .enumerate()
            .map(|(i, line)| ContextLine::new_rel(lineno, -(i as i32) - 1, line.clone()))
            .collect();
        let after = self
            .post_context
            .iter()
            .enumerate()
            .map(|(i, line)| ContextLine::new_rel(lineno, (i as i32) + 1, line.clone()))
            .collect();
        Some(Context {
            before,
            line,
            after,
        })
    }
}

impl From<&RawPythonFrame> for Frame {
    fn from(raw: &RawPythonFrame) -> Self {
        Frame {
            frame_id: FrameId::placeholder(),
            mangled_name: raw.function.clone(),
            line: raw.lineno,
            column: None,
            source: Some(raw.filename.clone()),
            in_app: raw.in_app(),
            resolved_name: Some(raw.function.clone()),
            lang: "python".to_string(),
            resolved: true,
            resolve_failure: None,

            junk_drawer: None,
            context: raw.get_context(),
            release: None,
            synthetic: raw.meta.synthetic,
            suspicious: false,
            module: raw.module.clone(),
            code_variables: raw.code_variables.clone(),
        }
    }
}

fn is_python_pseudo_filename(value: &str) -> bool {
    value.starts_with('<') && value.ends_with('>')
}

fn contains_python_pseudo_filename(value: &str) -> bool {
    value
        .rsplit(['/', '\\'])
        .next()
        .is_some_and(is_python_pseudo_filename)
}

#[cfg(test)]
mod test {
    use super::RawPythonFrame;

    #[test]
    fn test_in_app_normalization() {
        let cases = [
            (
                "site-packages frames are demoted",
                serde_json::json!({
                    "abs_path": "/usr/local/lib/python3.11/site-packages/redis/connection.py",
                    "filename": "redis/connection.py",
                    "function": "connect",
                    "module": "redis.connection",
                    "in_app": true,
                }),
                false,
            ),
            (
                "dist-packages filename is demoted without abs_path",
                serde_json::json!({
                    "filename": "/usr/lib/python3/dist-packages/click/core.py",
                    "function": "invoke",
                    "in_app": true,
                }),
                false,
            ),
            (
                "stdlib path is demoted",
                serde_json::json!({
                    "abs_path": "/usr/local/lib/python3.11/socket.py",
                    "filename": "socket.py",
                    "function": "getaddrinfo",
                    "in_app": true,
                }),
                false,
            ),
            (
                "stdlib module is demoted without path",
                serde_json::json!({
                    "filename": "functools.py",
                    "function": "__get__",
                    "module": "functools",
                    "in_app": true,
                }),
                false,
            ),
            (
                "unset in_app defaults true but library code is still demoted",
                serde_json::json!({
                    "abs_path": "/app/.venv/lib/python3.12/site-packages/kombu/utils/objects.py",
                    "filename": "kombu/utils/objects.py",
                    "function": "__get__",
                }),
                false,
            ),
            (
                "application frames stay in_app",
                serde_json::json!({
                    "abs_path": "/app/myapp/views.py",
                    "filename": "myapp/views.py",
                    "function": "get_user",
                    "module": "myapp.views",
                    "in_app": true,
                }),
                true,
            ),
            (
                "app module sharing a stdlib prefix stays in_app",
                serde_json::json!({
                    "abs_path": "/app/jsonapi/render.py",
                    "filename": "jsonapi/render.py",
                    "function": "render",
                    "module": "jsonapi.render",
                    "in_app": true,
                }),
                true,
            ),
            (
                "app package shadowing a stdlib module stays in_app",
                serde_json::json!({
                    "abs_path": "/app/logging/views.py",
                    "filename": "logging/views.py",
                    "function": "index",
                    "module": "logging.views",
                    "in_app": true,
                }),
                true,
            ),
            (
                "pathless stdlib package submodule is demoted",
                serde_json::json!({
                    "filename": "concurrent/futures/thread.py",
                    "function": "run",
                    "module": "concurrent.futures.thread",
                    "in_app": true,
                }),
                false,
            ),
            (
                "stdlib pseudo filename is demoted even with sdk-made abs_path",
                serde_json::json!({
                    "abs_path": "/app/<frozen importlib._bootstrap>",
                    "filename": "<frozen importlib._bootstrap>",
                    "function": "_find_and_load",
                    "module": "importlib._bootstrap",
                    "in_app": true,
                }),
                false,
            ),
            (
                "explicit client false is never promoted",
                serde_json::json!({
                    "abs_path": "/app/myapp/views.py",
                    "filename": "myapp/views.py",
                    "function": "get_user",
                    "module": "myapp.views",
                    "in_app": false,
                }),
                false,
            ),
        ];

        for (case, value, expected) in cases {
            let raw: RawPythonFrame = serde_json::from_value(value).unwrap();
            assert_eq!(raw.in_app(), expected, "{case}");
        }
    }

    #[test]
    fn test_unset_in_app_defaults_to_true() {
        let raw: RawPythonFrame = serde_json::from_value(serde_json::json!({
            "filename": "app.py",
            "function": "main",
        }))
        .unwrap();
        assert!(raw.meta.in_app);
    }
}
