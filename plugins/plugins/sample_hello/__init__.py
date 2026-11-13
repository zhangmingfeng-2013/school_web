"""
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
