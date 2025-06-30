__all__ = ["get_driver"]

import os
import re
import zipfile
from typing import overload
from selenium import webdriver
from selenium.webdriver.chrome.options import Options


def create_proxyauth_extension(
    proxy_host: str,
    proxy_port: int,
    proxy_user: str,
    proxy_pass: str,
    plugin_name: str = "proxy_auth_plugin.zip",
) -> str:
    """
    Создаёт zip-расширение для Chrome с настройками прокси + авторизации.
    Возвращает путь к созданному zip-файлу.
    """
    manifest_json = """
    {
        "version": "1.0.0",
        "manifest_version": 2,
        "name": "Chrome Proxy",
        "permissions": [
            "proxy",
            "tabs",
            "unlimitedStorage",
            "storage",
            "<all_urls>",
            "webRequest",
            "webRequestBlocking"
        ],
        "background": {
            "scripts": ["background.js"]
        },
        "minimum_chrome_version":"22.0.0"
    }
    """

    background_js = f"""
    var config = {{
            mode: "fixed_servers",
            rules: {{
                singleProxy: {{
                    scheme: "http",
                    host: "{proxy_host}",
                    port: parseInt({proxy_port})
                }},
                bypassList: []
            }}
        }};

    chrome.proxy.settings.set({{value: config, scope: "regular"}}, function() {{}});

    function callbackFn(details) {{
        return {{
            authCredentials: {{
                username: "{proxy_user}",
                password: "{proxy_pass}"
            }}
        }};
    }}

    chrome.webRequest.onAuthRequired.addListener(
        callbackFn,
        {{urls: ["<all_urls>"]}},
        ["blocking"]
    );
    """

    with zipfile.ZipFile(plugin_name, "w") as zp:
        zp.writestr("manifest.json", manifest_json)
        zp.writestr("background.js", background_js)

    return plugin_name


@overload
def get_driver(proxy: str, /) -> webdriver.Chrome:
    pass


@overload
def get_driver(
    proxy_user: str, proxy_pass: str, proxy_host: str, proxy_port: str, /
) -> webdriver.Chrome:
    pass


def get_driver(*args) -> webdriver.Chrome:

    if len(args) == 4:
        proxy_user, proxy_pass, proxy_host, proxy_port = args
    else:
        pattern = r"^(?P<user>[^:]+):(?P<password>[^@]+)@(?P<host>[^:]+):(?P<port>\d+)$"
        match = re.match(pattern, args[0])
        if match:
            proxy_user = match.group("user")
            proxy_pass = match.group("password")
            proxy_host = match.group("host")
            proxy_port = match.group("port")

    proxy_port = int(proxy_port)

    if proxy_host and proxy_port and proxy_user and proxy_pass:
        plugin_file = create_proxyauth_extension(
            proxy_host, proxy_port, proxy_user, proxy_pass
        )
        chrome_options = Options()
        chrome_options.add_extension(plugin_file)
        driver = webdriver.Chrome(options=chrome_options)
        if os.path.exists(plugin_file):
            os.remove(plugin_file)

    else:
        driver = webdriver.Chrome()

    return driver
