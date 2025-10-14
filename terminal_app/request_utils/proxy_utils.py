from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from seleniumwire import webdriver


def open_driver(
    proxy: str,
    fullscreen: bool = True,
    width: int = 1920,
    height: int = 1080,
    chromedriver_path: str = "/usr/bin/chromedriver",
) -> webdriver.Chrome:

    proxy_auth = f"http://{proxy}"

    seleniumwire_options = {
        "proxy": {
            "http": proxy_auth,
            "https": proxy_auth,
            "no_proxy": "localhost,127.0.0.1",
        }
    }

    chrome_options = Options()

    chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
    chrome_options.add_experimental_option("useAutomationExtension", False)
    chrome_options.add_experimental_option("detach", True)

    if fullscreen:
        chrome_options.add_argument("--start-maximized")  # Для полноэкранного режима
    else:
        chrome_options.add_argument(
            f"--window-size={width},{height}"
        )  # Для заданного размера

    service = Service(chromedriver_path)

    driver = webdriver.Chrome(
        service=service,
        options=chrome_options,
        seleniumwire_options=seleniumwire_options,
    )

    return driver
