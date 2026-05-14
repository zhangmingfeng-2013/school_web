"""
School_Web 多语言支持模块
"""
import json
import os

I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "i18n")
DEFAULT_LANG = "zh-CN"
SUPPORTED_LANGS = ["zh-CN", "en", "ja", "ko"]

_translations = {}
_lang_names = {}


def _load_translations(lang):
    """Load translation file for a language."""
    if lang in _translations:
        return _translations[lang]

    filepath = os.path.join(I18N_DIR, f"{lang}.json")
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        _translations[lang] = data
        _lang_names[lang] = data.get("_name", lang)
        return data
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _load_all():
    """Preload all supported languages."""
    for lang in SUPPORTED_LANGS:
        _load_translations(lang)


def get_lang_name(lang):
    """Get human-readable language name."""
    if lang in _lang_names:
        return _lang_names[lang]
    _load_translations(lang)
    return _lang_names.get(lang, lang)


def get_supported_langs():
    """Return list of supported language codes."""
    return SUPPORTED_LANGS


def _(key, lang=None, default=None, **kwargs):
    """
    Translate a key to the given language.
    Usage: _("nav_dashboard", lang="en") or _("nav_dashboard")
    With interpolation: _("backup_keep_n", n=5)
    """
    if lang is None:
        lang = DEFAULT_LANG
    if lang not in _translations:
        _load_translations(lang)
    trans = _translations.get(lang, {})
    val = trans.get(key, default if default is not None else key)
    if kwargs:
        try:
            val = val.format(**kwargs)
        except (KeyError, ValueError):
            pass
    return val


def detect_lang(request, session):
    """
    Detect best language from:
    1. Query param ?lang=
    2. Session stored preference
    3. Cookie (for non-logged-in users)
    4. Accept-Language header
    """
    # 1. Query param override
    qp_lang = request.args.get("lang", "").strip()
    if qp_lang in SUPPORTED_LANGS:
        return qp_lang

    # 2. Session preference
    sess_lang = session.get("lang", "")
    if sess_lang in SUPPORTED_LANGS:
        return sess_lang

    # 3. Cookie fallback
    cookie_lang = request.cookies.get("lang", "")
    if cookie_lang in SUPPORTED_LANGS:
        return cookie_lang

    # 4. Accept-Language header
    accept = request.headers.get("Accept-Language", "")
    if accept:
        # Simple parsing: take first language, normalize
        first = accept.split(",")[0].split(";")[0].strip().lower()
        # Map common codes
        lang_map = {
            "zh": "zh-CN", "zh-cn": "zh-CN", "zh-hans": "zh-CN",
            "zh-tw": "zh-CN", "zh-hant": "zh-CN",
            "en": "en", "en-us": "en", "en-gb": "en",
        }
        mapped = lang_map.get(first, "")
        if mapped in SUPPORTED_LANGS:
            return mapped

    return DEFAULT_LANG


# Preload on module import
_load_all()
