import pytest

def test_background_color(test_driver):
    tab = test_driver
    root_node = tab.call_method("DOM.getDocument")
    root_id = root_node['root']['nodeId']
    node = tab.call_method("DOM.querySelector", nodeId=root_id, selector="#h-wafer2")
    computedStyle = tab.call_method("CSS.getBackgroundColors", nodeId=node['nodeId'])
    print(repr(computedStyle))
    assert computedStyle['backgroundColors'] == ['rgb(31, 88, 129)']
