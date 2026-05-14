"""
日本語 Language Pack Plugin
日本語言語パック — Japanese language support for School_Web
"""
import os
import json
import sys

PLUGIN_NAME = "lang_ja"
LANG_CODE = "ja"
LANG_NAME = "日本語"

# 翻译文件路径
I18N_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "i18n")
TRANS_FILE = os.path.join(I18N_DIR, f"{LANG_CODE}.json")


def register(plugin_info):
    """プラグインロード時の処理 — Register language on plugin load"""
    _ensure_translation_file()
    _extend_supported_langs()
    # 注入CSSバッジ
    from plugins import register_template_block
    register_template_block(PLUGIN_NAME, {
        "name": "lang_ja_head",
        "template": '',
        "position": "head",
        "order": 100,
    })
    import flask
    try:
        flask.current_app.logger.info(f"🌏 Language '{LANG_NAME}' loaded by plugin '{PLUGIN_NAME}'")
    except Exception:
        pass


def unregister():
    """プラグインアンロード時の処理"""
    try:
        import flask
        flask.current_app.logger.info(f"🌏 Language '{LANG_NAME}' unloaded")
    except Exception:
        pass


def _ensure_translation_file():
    """
    翻訳ファイルが存在しない場合、自動生成する。
    プラグインディレクトリ内の ja.json テンプレートがあればコピーする。
    """
    if os.path.exists(TRANS_FILE):
        return

    # プラグイン内蔵テンプレートがあればそれを使用
    builtin = os.path.join(os.path.dirname(__file__), "ja.json")
    if os.path.exists(builtin):
        import shutil
        shutil.copy2(builtin, TRANS_FILE)
        return

    # なければ最小限の翻訳ファイルを生成
    _create_minimal_translations()


def _create_minimal_translations():
    """最小限の翻訳ファイルを生成"""
    minimal = {
        "_lang": LANG_CODE,
        "_name": LANG_NAME,
        "app_title": "オールインワンツールボックス Web版",
        "app_brand": "🛠 オールインワンツールボックス",
        "nav_dashboard": "ダッシュボード",
        "nav_admin": "管理",
        "nav_profile": "プロフィール",
        "nav_logout": "ログアウト",
        "login_title": "ログイン",
        "login_username": "ユーザー名",
        "login_password": "パスワード",
        "login_submit": "ログイン",
        "register_title": "登録",
        "dashboard_title": "ダッシュボード",
        "dashboard_hello": "こんにちは",
    }
    os.makedirs(I18N_DIR, exist_ok=True)
    with open(TRANS_FILE, "w", encoding="utf-8") as f:
        json.dump(minimal, f, indent=2, ensure_ascii=False)


def _extend_supported_langs():
    """SUPPORTED_LANGS に日本語を追加"""
    try:
        from i18n import SUPPORTED_LANGS
        if LANG_CODE not in SUPPORTED_LANGS:
            SUPPORTED_LANGS.append(LANG_CODE)
            print(f"  🌏 Added '{LANG_NAME}' ({LANG_CODE}) to supported languages")
    except ImportError:
        pass
