import tiktoken


def get_token_count(content: str):
    encoding = tiktoken.get_encoding("cl100k_base")
    return len(encoding.encode(content))
