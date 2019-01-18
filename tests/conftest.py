import pytest
from reprounzip.unpackers.dj import Driver
import pychrome

def pytest_addoption(parser):
    parser.addoption(
        "--site-url", action="store", default="http://rpzdj-repl.ay/", help="Site url"
    )


@pytest.fixture(scope="module")
def test_driver(request):
    site_url = request.config.getoption("--site-url")
    driver = Driver('playback')
    browser = pychrome.Browser(url=driver.cdp_url())
    tab = browser.new_tab()
    tab.start()
    seconds_since_something_happened = 0
    def reset_secs(**args):
        seconds_since_something_happened = 0
    tab.set_listener("Network.loadingFinished", reset_secs)
    tab.call_method("Page.navigate", url=site_url)
    while seconds_since_something_happened < 10:
        tab.wait(1)
        seconds_since_something_happened += 1

    tab.call_method("DOM.enable")
    tab.call_method("CSS.enable")
    return tab
