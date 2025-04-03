from enum import StrEnum

from tree_sitter import Language

from .exceptions import UnsupportedLanguage


class ProgrammingLanguage(StrEnum):
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    PYTHON = "python"
    TSX = "tsx"
    RUST = "rust"
    GO = "go"
    BASH = "bash"

    # CPP = "cpp"
    # C_SHARP = "c_sharp"
    # C = "c"
    # CSS = "css"
    # PHP = "php"
    # JSON = "json"
    # ELM = "elm"
    # ELISP = "elisp"
    # ELIXIR = "elixir"
    # EMBEDDED_TEMPLATE = "embedded_template"
    # HTML = "html"
    # JAVA = "java"
    # LUA = "lua"
    # OCAML = "ocaml"
    # QL = "ql"
    # RESCRIPT = "rescript"
    # RUBY = "ruby"
    # SYSTEMRDL = "systemrdl"
    # TOML = "toml"
    # SOLIDITY = "solidity"


def get_parser_language(lang: ProgrammingLanguage) -> Language:
    match lang:
        case ProgrammingLanguage.TSX:
            from tree_sitter_typescript import language_tsx

            return Language(language_tsx())
        case ProgrammingLanguage.TYPESCRIPT:
            from tree_sitter_typescript import language_typescript

            return Language(language_typescript())
        case ProgrammingLanguage.JAVASCRIPT:
            from tree_sitter_javascript import language

            return Language(language())
        case ProgrammingLanguage.PYTHON:
            from tree_sitter_python import language

            return Language(language())
        case ProgrammingLanguage.RUST:
            from tree_sitter_rust import language

            return Language(language())
        case ProgrammingLanguage.GO:
            from tree_sitter_go import language

            return Language(language())
        case ProgrammingLanguage.BASH:
            from tree_sitter_bash import language

            return Language(language())
        case _:
            raise UnsupportedLanguage(lang)
