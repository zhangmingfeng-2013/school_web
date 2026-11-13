"""
School_Web 插件系统
支持动态加载、卸载和管理插件
"""
import os
import json
import importlib
import sys
import traceback

PLUGINS_DIR = os.path.join(os.path.dirname(__file__), "plugins")

# 已加载的插件 {name: module}
_loaded_plugins = {}

# 插件 hook 注册表
_plugin_hooks = {
    "menu_items": [],       # 菜单项
    "template_blocks": [],  # 模板注入块
    "static_routes": [],    # 静态文件路由
    "api_routes": [],       # API 路由
}


def discover_plugins():
    """
    扫描 plugins/ 目录，返回所有可用插件列表。
    每个插件是一个子目录，包含 plugin.json 和 __init__.py。
    """
    plugins = []
    if not os.path.isdir(PLUGINS_DIR):
        return plugins

    for name in os.listdir(PLUGINS_DIR):
        plugin_dir = os.path.join(PLUGINS_DIR, name)
        if not os.path.isdir(plugin_dir):
            continue
        manifest_path = os.path.join(plugin_dir, "plugin.json")
        init_path = os.path.join(plugin_dir, "__init__.py")
        if not os.path.exists(manifest_path):
            continue

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
        except (json.JSONDecodeError, IOError):
            continue

        plugins.append({
            "name": name,
            "dir": plugin_dir,
            "manifest": manifest,
            "has_init": os.path.exists(init_path),
            "loaded": name in _loaded_plugins,
        })

    return plugins


def load_plugin(name):
    """
    加载指定插件。返回 (success, message)。
    """
    if name in _loaded_plugins:
        return True, f"Plugin '{name}' already loaded"

    plugin_dir = os.path.join(PLUGINS_DIR, name)
    if not os.path.isdir(plugin_dir):
        return False, f"Plugin directory not found: {plugin_dir}"

    manifest_path = os.path.join(plugin_dir, "plugin.json")
    if not os.path.exists(manifest_path):
        return False, f"plugin.json not found for '{name}'"

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        return False, f"Failed to read plugin.json: {e}"

    init_path = os.path.join(plugin_dir, "__init__.py")
    if not os.path.exists(init_path):
        # 无代码的 manifest-only 插件（仅用于菜单注册）
        _loaded_plugins[name] = {"manifest": manifest, "module": None}
        return True, f"Plugin '{name}' loaded (manifest only)"

    try:
        # 动态导入
        import importlib.util
        module_name = f"plugins.{name}"
        spec = importlib.util.spec_from_file_location(
            module_name, init_path,
            submodule_search_locations=[plugin_dir]
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)

        plugin_info = {"manifest": manifest, "module": module}
        _loaded_plugins[name] = plugin_info

        # 调用插件的 register 函数
        if hasattr(module, "register"):
            module.register(plugin_info)

        return True, f"Plugin '{manifest.get('name', name)}' v{manifest.get('version', '0.1')} loaded"
    except Exception as e:
        traceback.print_exc()
        return False, f"Failed to load plugin '{name}': {e}"


def unload_plugin(name):
    """
    卸载指定插件。
    """
    if name not in _loaded_plugins:
        return False, f"Plugin '{name}' not loaded"

    plugin = _loaded_plugins[name]

    # 调用插件的 unregister 函数
    if plugin.get("module") and hasattr(plugin["module"], "unregister"):
        try:
            plugin["module"].unregister()
        except Exception:
            pass

    del _loaded_plugins[name]

    # 清理 sys.modules
    module_name = f"plugins.{name}"
    if module_name in sys.modules:
        del sys.modules[module_name]

    return True, f"Plugin '{name}' unloaded"


def get_loaded_plugins():
    """返回已加载的插件列表"""
    return list(_loaded_plugins.keys())


def register_menu_item(plugin_name, item):
    """
    注册菜单项。由插件调用。
    item: { "label": "菜单名", "url": "/path", "icon": "📅", "permission": "all", "order": 100 }
    """
    _plugin_hooks["menu_items"].append({
        "plugin": plugin_name,
        **item
    })


def get_menu_items(user_permission="guest"):
    """
    获取当前用户可见的菜单项。
    """
    items = []
    for item in _plugin_hooks["menu_items"]:
        req_perm = item.get("permission", "all")
        if _check_permission(user_permission, req_perm):
            items.append(item)
    items.sort(key=lambda x: x.get("order", 100))
    return items


def register_template_block(plugin_name, block):
    """
    注册模板注入块。
    block: { "name": "unique_name", "template": "<html片段>", "position": "nav|footer|head", "order": 100 }
    """
    _plugin_hooks["template_blocks"].append({
        "plugin": plugin_name,
        **block
    })


def get_template_blocks(position="nav"):
    """
    获取指定位置的模板注入块。
    """
    blocks = [b for b in _plugin_hooks["template_blocks"] if b.get("position") == position]
    blocks.sort(key=lambda x: x.get("order", 100))
    return blocks


def _check_permission(user_perm, required):
    """检查用户权限是否满足要求"""
    if required == "all":
        return True
    perm_levels = {"guest": 0, "user": 1, "vip": 2, "administrator": 3}
    return perm_levels.get(user_perm, 0) >= perm_levels.get(required, 0)


# 创建示例插件
def _create_sample_plugin():
    """创建一个示例插件，展示插件系统的用法"""
    sample_dir = os.path.join(PLUGINS_DIR, "sample_hello")
    os.makedirs(sample_dir, exist_ok=True)

    manifest = {
        "name": "Hello World Plugin",
        "version": "1.0.0",
        "description": "一个示例插件，展示插件系统的基本功能",
        "author": "School_Web",
        "license": "MIT",
    }
    with open(os.path.join(sample_dir, "plugin.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    init_code = '''"""
Hello World 示例插件
"""
from plugins import register_menu_item, register_template_block

PLUGIN_NAME = "sample_hello"


def register(plugin_info):
    """插件加载时调用"""
    # 注册菜单项
    register_menu_item(PLUGIN_NAME, {
        "label": "👋 Hello",
        "url": "/plugin/hello",
        "icon": "👋",
        "permission": "all",
        "order": 200,
    })

    # 注册底部模板注入
    register_template_block(PLUGIN_NAME, {
        "name": "hello_footer",
        "template": '<div class="text-center text-muted small py-2">⚡ Hello World Plugin 已运行</div>',
        "position": "footer",
        "order": 100,
    })


def unregister():
    """插件卸载时调用"""
    pass
'''
    with open(os.path.join(sample_dir, "__init__.py"), "w", encoding="utf-8") as f:
        f.write(init_code)


# 首次导入时创建示例插件
_create_sample_plugin()
