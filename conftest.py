# conftest.py — project root
# Block the vcr-proxy pytest plugin so coverage can track all vcr_proxy imports.
# The plugin entry point loads vcr_proxy modules before pytest-cov starts,
# causing those modules to show 0% coverage.
collect_ignore: list[str] = []
pytest_plugins: list[str] = []


def pytest_configure(config):
    # Unregister the vcr-proxy plugin if it was loaded via entry points
    plugin_manager = config.pluginmanager
    plugin = plugin_manager.get_plugin("vcr-proxy")
    if plugin is not None:
        plugin_manager.unregister(plugin)
