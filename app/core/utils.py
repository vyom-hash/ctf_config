import os
import hashlib


def generate_md5(content: str) -> str:
    return hashlib.md5(content.encode("utf-8")).hexdigest()
