import bcrypt

import hashlib

import base64

from cryptography.fernet import Fernet

from cryptography.hazmat.primitives import hashes

from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

import os



# Use a hardcoded key for now (in production, this should be from environment)

ENCRYPTION_KEY = b'EZZQkxvNvxOjmskuNfi7IvDJdb0ZoPeucRDSGHoxVO8='

cipher_suite = Fernet(ENCRYPTION_KEY)



def get_encryption_key():

    """Get encryption key (for future use with environment variables)"""

    return ENCRYPTION_KEY



def hash_password(password: str) -> bytes:

    """Hash password using bcrypt (for authentication)"""

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())



def verify_password(password: str, hashed: bytes) -> bool:

    """Verify password against bcrypt hash"""

    return bcrypt.checkpw(password.encode(), hashed)



def encrypt_password(password: str) -> str:

    """

    Encrypt password using Fernet symmetric encryption

    Returns base64 encoded encrypted string

    """

    if not password:

        return ""

    

    # Convert to bytes if needed

    if isinstance(password, str):

        password = password.encode()

    

    # Encrypt the password

    encrypted_password = cipher_suite.encrypt(password)

    

    # Return as base64 string for storage

    return base64.urlsafe_b64encode(encrypted_password).decode()



def decrypt_password(encrypted_password: str) -> str:

    """

    Decrypt password from base64 encoded encrypted string

    Returns original plain text password

    """

    if not encrypted_password:

        return ""

    

    try:

        # Decode from base64

        encrypted_bytes = base64.urlsafe_b64decode(encrypted_password.encode())

        

        # Decrypt the password

        decrypted_password = cipher_suite.decrypt(encrypted_bytes)

        

        # Return as string

        return decrypted_password.decode()

    except Exception as e:

        # Re-raise the exception so the calling function can handle it

        raise Exception(f"Password decryption failed: {e}")



def safe_decrypt_password(encrypted_password: str) -> str:

    """

    Safely decrypt password with fallback for plain text

    Returns decrypted password or original if decryption fails

    """

    if not encrypted_password:

        return ""

    

    try:

        return decrypt_password(encrypted_password)

    except Exception:

        # If decryption fails, return as-is (plain text)

        return encrypted_password



def sha256_hash(text: str) -> str:

    """

    Generate SHA-256 hash of text (for one-way hashing if needed)

    """

    return hashlib.sha256(text.encode()).hexdigest()