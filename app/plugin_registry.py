"""In-memory registry of plugin manifests uploaded by workers."""

from __future__ import annotations


class PluginRegistry:
    """In-memory registry of plugin manifests uploaded by workers."""

    def __init__(self):
        self._plugins: dict[str, dict] = {}  # name -> manifest dict

    def register(self, manifest: dict) -> None:
        """Register or update a plugin manifest."""
        name = manifest["name"]
        self._plugins[name] = manifest

    def get(self, name: str) -> dict | None:
        return self._plugins.get(name)

    def list_all(self) -> list[dict]:
        return list(self._plugins.values())

    def has_plugin(self, name: str) -> bool:
        return name in self._plugins

    def get_task_type(self, plugin: str, task_type: str) -> dict | None:
        """Get a specific task type definition from a plugin manifest."""
        manifest = self.get(plugin)
        if not manifest:
            return None
        for tt in manifest.get("capabilities", {}).get("task_types", []):
            if tt["name"] == task_type:
                return tt
        return None

    def validate_task(self, plugin: str, task_type: str, params: dict) -> list[str]:
        """
        Validate a task against its plugin manifest.
        Returns list of error messages (empty if valid).
        Checks: plugin exists, task_type exists, required params present, enum values valid.
        """
        errors = []
        if not self.has_plugin(plugin):
            errors.append(f"Unknown plugin: {plugin}")
            return errors
        tt = self.get_task_type(plugin, task_type)
        if not tt:
            errors.append(f"Unknown task type '{task_type}' for plugin '{plugin}'")
            return errors
        schema = tt.get("params_schema", {})
        for param_name, param_def in schema.items():
            if param_def.get("required", False) and param_name not in params:
                errors.append(f"Missing required param '{param_name}' for {plugin}/{task_type}")
            if param_name in params and "enum" in param_def:
                if params[param_name] not in param_def["enum"]:
                    errors.append(f"Invalid value '{params[param_name]}' for '{param_name}', must be one of {param_def['enum']}")
        return errors
