class UnsupportedLanguage(Exception):
    def __init__(self, language: str):
        self.language = language

    def __str__(self):
        return f"Unsupported language: {self.language}"
