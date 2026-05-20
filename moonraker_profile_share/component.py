from __future__ import annotations

from typing import Any, Dict, Optional

from .store import (
    InMemoryNamespaceDB,
    NamespaceProfileStore,
    ProfileNotFoundError,
    ProfileValidationError,
    StoreSettings,
)


class ProfileShareComponent:
    def __init__(self, config: Any):
        self.config = config
        self.server = self._get_config_value("get_server")

        namespace = self._get_config_setting("namespace", "moonraker_profile_share")
        max_profiles = int(self._get_config_setting("max_profiles", 500))
        max_payload_bytes = int(self._get_config_setting("max_payload_bytes", 2 * 1024 * 1024))
        self.enabled = bool(self._get_config_setting("enabled", True))

        db = self._lookup_database_component()
        self.store = NamespaceProfileStore(
            db,
            StoreSettings(
                namespace=namespace,
                max_profiles=max_profiles,
                max_payload_bytes=max_payload_bytes,
            ),
        )

        if self.enabled:
            self._register_endpoints()

    async def component_init(self) -> None:
        if self.enabled:
            await self.store.initialize()

    async def _handle_list_profiles(self, web_request: Any) -> Dict[str, Any]:
        profile_type = self._request_get(web_request, "type")
        printer_id = self._request_get(web_request, "printer_id")
        profiles = await self.store.list_profiles(profile_type=profile_type, printer_id=printer_id)
        return {
            "namespace": self.store.settings.namespace,
            "count": len(profiles),
            "profiles": [self._public_profile(profile) for profile in profiles],
        }

    async def _handle_get_profile(self, web_request: Any) -> Dict[str, Any]:
        profile_id = self._required_request_field(web_request, "profile_id")
        try:
            profile = await self.store.get_profile(profile_id)
        except ProfileNotFoundError as exc:
            raise self._server_error(f"Profile '{profile_id}' not found") from exc
        return self._public_profile(profile)

    async def _handle_create_profile(self, web_request: Any) -> Dict[str, Any]:
        payload = self._request_json(web_request)
        try:
            profile = await self.store.create_profile(payload)
        except ProfileValidationError as exc:
            raise self._server_error(str(exc)) from exc
        return self._public_profile(profile)

    async def _handle_update_profile(self, web_request: Any) -> Dict[str, Any]:
        profile_id = self._required_request_field(web_request, "profile_id")
        payload = self._request_json(web_request)
        try:
            profile = await self.store.update_profile(profile_id, payload)
        except ProfileValidationError as exc:
            raise self._server_error(str(exc)) from exc
        except ProfileNotFoundError as exc:
            raise self._server_error(f"Profile '{profile_id}' not found") from exc
        return self._public_profile(profile)

    async def _handle_delete_profile(self, web_request: Any) -> Dict[str, Any]:
        profile_id = self._required_request_field(web_request, "profile_id")
        try:
            await self.store.delete_profile(profile_id)
        except ProfileNotFoundError as exc:
            raise self._server_error(f"Profile '{profile_id}' not found") from exc
        return {"deleted": profile_id}

    def _register_endpoints(self) -> None:
        registrar = getattr(self.server, "register_endpoint", None)
        if registrar is None:
            return

        registrar(
            "/server/profile_share/profiles",
            ["GET"],
            self._handle_list_profiles,
            auth_required=True,
        )
        registrar(
            "/server/profile_share/profiles",
            ["POST"],
            self._handle_create_profile,
            auth_required=True,
        )
        registrar(
            "/server/profile_share/profiles/{profile_id}",
            ["GET"],
            self._handle_get_profile,
            auth_required=True,
        )
        registrar(
            "/server/profile_share/profiles/{profile_id}",
            ["PUT"],
            self._handle_update_profile,
            auth_required=True,
        )
        registrar(
            "/server/profile_share/profiles/{profile_id}",
            ["DELETE"],
            self._handle_delete_profile,
            auth_required=True,
        )

    def _public_profile(self, profile: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": profile["id"],
            "name": profile["name"],
            "type": profile["type"],
            "printer_id": profile.get("printer_id"),
            "source": profile.get("source"),
            "slicer": profile.get("slicer"),
            "version": profile.get("version"),
            "created_at": profile["created_at"],
            "updated_at": profile["updated_at"],
            "profile": profile["payload"],
        }

    def _lookup_database_component(self) -> Any:
        if self.server is None:
            return InMemoryNamespaceDB()

        lookup = getattr(self.server, "lookup_component", None)
        if lookup is None:
            return InMemoryNamespaceDB()

        for candidate in ("database", "db"):
            try:
                return lookup(candidate)
            except Exception:
                continue
        return InMemoryNamespaceDB()

    def _server_error(self, msg: str) -> Exception:
        if self.server is not None:
            error_factory = getattr(self.server, "error", None)
            if error_factory is not None:
                return error_factory(msg)
        return ValueError(msg)

    def _get_config_value(self, name: str) -> Optional[Any]:
        getter = getattr(self.config, name, None)
        if getter is None:
            return None
        return getter()

    def _get_config_setting(self, key: str, default: Any) -> Any:
        for getter_name in ("get", "getint", "getboolean"):
            getter = getattr(self.config, getter_name, None)
            if getter is None:
                continue
            try:
                value = getter(key, default)
                return value
            except Exception:
                continue
        if isinstance(self.config, dict):
            return self.config.get(key, default)
        return default

    def _request_json(self, web_request: Any) -> Dict[str, Any]:
        if isinstance(web_request, dict):
            return web_request
        for attr in ("get_json", "json"):
            value = getattr(web_request, attr, None)
            if value is None:
                continue
            payload = value() if callable(value) else value
            if isinstance(payload, dict):
                return payload
        return {}

    def _request_get(self, web_request: Any, key: str) -> Optional[str]:
        if isinstance(web_request, dict):
            value = web_request.get(key)
            return str(value) if value is not None else None

        for method_name in ("get_str", "get"):
            method = getattr(web_request, method_name, None)
            if method is None:
                continue
            try:
                value = method(key)
            except TypeError:
                value = method(key, None)
            except Exception:
                continue
            if value is None:
                continue
            value = str(value)
            if value:
                return value
        return None

    def _required_request_field(self, web_request: Any, key: str) -> str:
        value = self._request_get(web_request, key)
        if not value:
            raise self._server_error(f"Missing required path/query field '{key}'")
        return value
