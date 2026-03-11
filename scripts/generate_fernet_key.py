#!/usr/bin/env python3
"""
Utility script to generate a secure Fernet key for symmetric encryption.
Usage:
    python3 scripts/generate_fernet_key.py
"""
try:
    from cryptography.fernet import Fernet
except ImportError:
    print("Error: 'cryptography' library not found. Please install it using 'pip install cryptography'.")
    exit(1)

def generate_key():
    key = Fernet.generate_key()
    print("\n--- New Fernet Encryption Key ---")
    print(key.decode())
    print("----------------------------------\n")
    print("Important: Copy this key to your .env file as ENCRYPTION_KEY.")
    print("Keep this key secret. If lost, you cannot decrypt your data.\n")

if __name__ == "__main__":
    generate_key()
