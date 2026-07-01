"""
Cloud — cloud variable IO device.

Manages cloud variable synchronization. In the official scratch-vm, this is
backed by a WebSocket connection to the Scratch cloud data server.

In py-scratch, the provider is a pluggable stub — the module tracks cloud
variable state locally and provides the hook for a real provider.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .runtime import Runtime
    from .target import Variable


class Cloud:
    """Cloud IO device — bridges cloud variable updates to a provider."""

    def __init__(self, runtime: Runtime) -> None:
        self.runtime = runtime
        self.provider: CloudProvider | None = None
        self.stage: Any = None  # Target — set by Runtime

    def set_provider(self, provider: CloudProvider) -> None:
        """Connect a cloud data provider (WebSocket client, etc.)."""
        self.provider = provider

    def set_stage(self, stage: Any) -> None:
        """Set the stage target that owns cloud variables."""
        self.stage = stage

    def request_update_variable(self, name: str, value: Any) -> None:
        """Send a cloud variable update to the provider."""
        if self.provider is not None:
            self.provider.update_variable(name, value)

    def request_create_variable(self, variable: Variable) -> None:
        """Request creation of a new cloud variable."""
        if self.runtime.can_add_cloud_variable():
            if self.provider is not None:
                self.provider.create_variable(variable.name, variable.value)

    def update_cloud_variable(self, var_update: dict[str, Any]) -> None:
        """Apply an incoming cloud variable update from the server."""
        name = var_update.get('name', '')
        value = var_update.get('value', 0)
        if self.stage is not None:
            var = self.stage.lookup_variable(name)
            if var is not None:
                var.value = value


class CloudProvider:
    """Abstract base for a cloud data provider (WebSocket, etc.)."""

    def update_variable(self, name: str, value: Any) -> None:
        """Send a variable update to the cloud server."""

    def create_variable(self, name: str, value: Any) -> None:
        """Create a variable on the cloud server."""
