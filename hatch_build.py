"""Hatchling build hook: keep the repository's .gitignore out of the sdist.

Hatchling always adds the project's .gitignore to a source distribution, and
`exclude` cannot remove it. This file lists local, personal entries, so it is
dropped here. The hook runs for the sdist target only (see pyproject.toml).
"""

from hatchling.builders.hooks.plugin.interface import BuildHookInterface


class DropGitignoreHook(BuildHookInterface):
    PLUGIN_NAME = "drop-gitignore"

    def initialize(self, version, build_data):
        forced = build_data.get("force_include", {})
        for source in [src for src, dest in forced.items() if dest == ".gitignore"]:
            del forced[source]
