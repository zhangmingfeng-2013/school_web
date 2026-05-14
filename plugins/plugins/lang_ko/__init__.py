"""
한국어 Language Pack Plugin
한국어 언어팩 — Korean language support for School_Web
"""
import os
import json

PLUGIN_NAME = "lang_ko"
LANG_CODE = "ko"
LANG_NAME = "한국어"

# Translation file path
I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "i18n")
TRANS_FILE = os.path.join(I18N_DIR, f"{LANG_CODE}.json")


def register(plugin_info):
    """Register language on plugin load"""
    _ensure_translation_file()
    _extend_supported_langs()
    from plugins import register_template_block
    register_template_block(PLUGIN_NAME, {
        "name": "lang_ko_head",
        "template": '',
        "position": "head",
        "order": 101,
    })
    import flask
    try:
        flask.current_app.logger.info(f"🌏 Language '{LANG_NAME}' loaded by plugin '{PLUGIN_NAME}'")
    except Exception:
        pass


def unregister():
    """Cleanup on plugin unload"""
    try:
        import flask
        flask.current_app.logger.info(f"🌏 Language '{LANG_NAME}' unloaded")
    except Exception:
        pass


def _ensure_translation_file():
    """Create translation file if not exists"""
    if os.path.exists(TRANS_FILE):
        return
    builtin = os.path.join(os.path.dirname(__file__), "ko.json")
    if os.path.exists(builtin):
        import shutil
        shutil.copy2(builtin, TRANS_FILE)
        return
    _create_minimal_translations()


def _create_minimal_translations():
    """Generate minimal translation file"""
    minimal = {
        "_lang": LANG_CODE,
        "_name": LANG_NAME,
        "app_title": "올인원 도구상자 웹 버전",
        "app_brand": "🛠 올인원 도구상자",
        "nav_dashboard": "대시보드",
        "nav_admin": "관리",
        "nav_profile": "프로필",
        "nav_logout": "로그아웃",
        "login_title": "로그인",
        "login_username": "사용자 이름",
        "login_password": "비밀번호",
        "login_submit": "로그인",
        "register_title": "회원가입",
        "dashboard_title": "대시보드",
        "dashboard_hello": "안녕하세요",
    }
    os.makedirs(I18N_DIR, exist_ok=True)
    with open(TRANS_FILE, "w", encoding="utf-8") as f:
        json.dump(minimal, f, indent=2, ensure_ascii=False)


def _extend_supported_langs():
    """Add Korean to SUPPORTED_LANGS"""
    try:
        from i18n import SUPPORTED_LANGS
        if LANG_CODE not in SUPPORTED_LANGS:
            SUPPORTED_LANGS.append(LANG_CODE)
            print(f"  🌏 Added '{LANG_NAME}' ({LANG_CODE}) to supported languages")
    except ImportError:
        pass
