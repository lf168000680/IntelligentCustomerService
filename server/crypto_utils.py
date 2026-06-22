"""
API Key 加密存储工具
使用 AES-256-GCM 加密，密钥来自环境变量或本地文件
"""
import os
import base64
import hashlib
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


# 密钥来源优先级:
# 1. 环境变量 ENCRYPTION_KEY
# 2. 本地密钥文件 data/.encryption_key (首次自动生成)
def _get_or_create_key() -> bytes:
    """获取或创建加密密钥 (32 bytes for AES-256)"""
    env_key = os.environ.get("ENCRYPTION_KEY", "")
    if env_key and env_key != "change_this_to_random_32_bytes":
        # 从环境变量派生32字节密钥
        return hashlib.sha256(env_key.encode()).digest()

    # 从本地文件读取
    key_file = Path(__file__).parent.parent / "data" / ".encryption_key"
    if key_file.exists():
        return key_file.read_bytes()

    # 自动生成并保存
    key_file.parent.mkdir(parents=True, exist_ok=True)
    new_key = AESGCM.generate_key(bit_length=256)
    key_file.write_bytes(new_key)
    # 设置权限 (仅 Windows/Linux)
    try:
        os.chmod(key_file, 0o600)
    except:
        pass
    return new_key


# 全局密钥实例
_ENCRYPTION_KEY = _get_or_create_key()


def encrypt_api_key(plaintext: str) -> str:
    """
    加密 API Key

    格式: base64(nonce + ciphertext)
    nonce: 12 bytes (AES-GCM 标准)
    """
    if not plaintext:
        return ""

    aesgcm = AESGCM(_ENCRYPTION_KEY)
    nonce = os.urandom(12)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    # nonce (12) + ciphertext
    combined = nonce + ciphertext
    return base64.b64encode(combined).decode("ascii")


def decrypt_api_key(encrypted: str) -> str:
    """
    解密 API Key

    输入: base64(nonce + ciphertext)
    输出: 明文 API Key
    """
    if not encrypted:
        return ""

    try:
        aesgcm = AESGCM(_ENCRYPTION_KEY)
        combined = base64.b64decode(encrypted)
        nonce = combined[:12]
        ciphertext = combined[12:]
        plaintext = aesgcm.decrypt(nonce, ciphertext, None)
        return plaintext.decode("utf-8")
    except Exception:
        # 可能是未加密的旧数据，原样返回
        return encrypted


def mask_api_key(key: str) -> str:
    """脱敏显示 API Key: sk-ant-xxxx...xxxx"""
    if not key:
        return ""
    if len(key) <= 12:
        return key[:4] + "****"
    return key[:8] + "****" + key[-4:]
