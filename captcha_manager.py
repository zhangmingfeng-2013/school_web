"""
验证码管理器 — MySQL 共享存储
============================

验证码挑战保存在主数据库中，所有 Gunicorn worker 共享同一份状态。
验证码正文不会写入数据库；数据库仅保存使用应用密钥计算的 HMAC 摘要。
验证使用 InnoDB 行锁和事务实现一次性消费，同一个验证码最多成功一次。
"""

import hashlib
import hmac
import logging
import secrets
import threading
import uuid
from collections.abc import Callable
from typing import Any


MAX_AGE = 300
_TABLE_NAME = "captcha_challenges"
_CHARS = "23456789abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ"

_connection_factory: Callable[[], Any] | None = None
_digest_key: bytes | None = None
_schema_ready = False
_schema_lock = threading.Lock()
_logger = logging.getLogger(__name__)


def configure(connection_factory: Callable[[], Any], digest_key: str | bytes) -> None:
    """注入主数据库连接工厂和跨 worker 一致的验证码摘要密钥。"""
    if not callable(connection_factory):
        raise TypeError("connection_factory 必须可调用")

    key = digest_key.encode("utf-8") if isinstance(digest_key, str) else bytes(digest_key)
    if not key:
        raise ValueError("digest_key 不能为空")

    global _connection_factory, _digest_key, _schema_ready
    with _schema_lock:
        _connection_factory = connection_factory
        _digest_key = key
        _schema_ready = False


def init_schema() -> bool:
    """幂等创建验证码表；数据库暂时不可用时允许后续请求重试。"""
    global _schema_ready
    if _schema_ready:
        return True

    with _schema_lock:
        if _schema_ready:
            return True

        conn = _connect()
        if conn is None:
            return False

        cursor = None
        try:
            cursor = conn.cursor()
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {_TABLE_NAME} (
                    captcha_key CHAR(32) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
                    code_digest BINARY(32) NOT NULL,
                    created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
                    expires_at DATETIME(6) NOT NULL,
                    PRIMARY KEY (captcha_key),
                    KEY idx_captcha_expires_at (expires_at)
                ) ENGINE=InnoDB DEFAULT CHARSET=ascii COLLATE=ascii_bin
                """
            )
            conn.commit()
            _schema_ready = True
            return True
        except Exception:
            _rollback(conn)
            _logger.exception("初始化验证码数据表失败")
            return False
        finally:
            _close(cursor, conn)


def generate() -> tuple[str, str] | None:
    """生成并持久化验证码，成功返回 ``(key, code)``，失败返回 ``None``。"""
    if not init_schema():
        return None

    key = uuid.uuid4().hex
    code = "".join(secrets.choice(_CHARS) for _ in range(6)).lower()
    digest = _make_digest(key, code)
    if digest is None:
        return None

    conn = _connect()
    if conn is None:
        return None

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"DELETE FROM {_TABLE_NAME} "
            "WHERE expires_at <= UTC_TIMESTAMP(6) LIMIT 1000"
        )
        cursor.execute(
            f"""
            INSERT INTO {_TABLE_NAME} (captcha_key, code_digest, expires_at)
            VALUES (%s, %s, DATE_ADD(UTC_TIMESTAMP(6), INTERVAL %s SECOND))
            """,
            (key, digest, MAX_AGE),
        )
        conn.commit()
        return key, code
    except Exception:
        _rollback(conn)
        _mark_schema_unready()
        _logger.exception("保存验证码失败")
        return None
    finally:
        _close(cursor, conn)


def verify(key: str, user_input: str) -> bool:
    """原子校验并消费验证码；正确、错误或过期的挑战都会被一次性消费。"""
    if not _valid_key(key) or not user_input:
        return False
    if not init_schema():
        return False

    normalized_input = user_input.strip().lower()
    candidate_digest = _make_digest(key, normalized_input)
    if candidate_digest is None:
        return False

    conn = _connect()
    if conn is None:
        return False

    cursor = None
    try:
        conn.begin()
        cursor = conn.cursor()
        cursor.execute(
            f"""
            SELECT code_digest, expires_at > UTC_TIMESTAMP(6)
            FROM {_TABLE_NAME}
            WHERE captcha_key = %s
            FOR UPDATE
            """,
            (key,),
        )
        row = cursor.fetchone()
        if row is None:
            conn.commit()
            return False

        cursor.execute(
            f"DELETE FROM {_TABLE_NAME} WHERE captcha_key = %s",
            (key,),
        )
        consumed = cursor.rowcount == 1
        conn.commit()

        stored_digest = bytes(row[0])
        not_expired = bool(row[1])
        return consumed and not_expired and hmac.compare_digest(
            candidate_digest, stored_digest
        )
    except Exception:
        _rollback(conn)
        _mark_schema_unready()
        _logger.exception("校验验证码失败")
        return False
    finally:
        _close(cursor, conn)


def cleanup_expired(limit: int = 1000) -> int | None:
    """分批删除过期挑战，成功返回删除数量，失败返回 ``None``。"""
    if not init_schema():
        return None

    limit = max(1, min(int(limit), 10000))
    conn = _connect()
    if conn is None:
        return None

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute(
            f"DELETE FROM {_TABLE_NAME} "
            "WHERE expires_at <= UTC_TIMESTAMP(6) LIMIT %s",
            (limit,),
        )
        deleted = cursor.rowcount
        conn.commit()
        return deleted
    except Exception:
        _rollback(conn)
        _mark_schema_unready()
        _logger.exception("清理过期验证码失败")
        return None
    finally:
        _close(cursor, conn)


def _connect():
    factory = _connection_factory
    if factory is None:
        _logger.error("验证码数据库连接工厂尚未配置")
        return None

    try:
        return factory()
    except Exception:
        _logger.exception("连接验证码数据库失败")
        return None


def _make_digest(key: str, code: str) -> bytes | None:
    digest_key = _digest_key
    if digest_key is None:
        _logger.error("验证码摘要密钥尚未配置")
        return None
    payload = f"{key}:{code}".encode("utf-8")
    return hmac.new(digest_key, payload, hashlib.sha256).digest()


def _valid_key(key: str) -> bool:
    if not isinstance(key, str) or len(key) != 32:
        return False
    try:
        return uuid.UUID(hex=key).hex == key.lower()
    except ValueError:
        return False


def _mark_schema_unready() -> None:
    global _schema_ready
    with _schema_lock:
        _schema_ready = False


def _rollback(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        pass


def _close(cursor, conn) -> None:
    if cursor is not None:
        try:
            cursor.close()
        except Exception:
            pass
    try:
        conn.close()
    except Exception:
        pass
