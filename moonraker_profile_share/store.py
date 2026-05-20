from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4


_ALLOWED_PROFILE_TYPES = {"printer", "process", "filament"}


class ProfileValidationError(ValueError):
    pass


class ProfileNotFoundError(KeyError):
    pass


@dataclass
class StoreSettings:
    namespace: str = "moonraker_profile_share"
    max_profiles: int = 500
    max_payload_bytes: int = 2 * 1024 * 1024


class NamespaceProfileStore:
    def __init__(self, db: Any, settings: StoreSettings):
        self.db = db
        self.settings = settings

    async def initialize(self) -> None:
        register = getattr(self.db, "register_local_namespace", None)
        if register is not None:
            result = register(self.settings.namespace)
            if hasattr(result, "__await__"):
                await result

        if await self._safe_get_item("__index__") is None:
            await self._set_item("__index__", [])

    async def list_profiles(
        self,
        profile_type: Optional[str] = None,
        printer_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        profiles: List[Dict[str, Any]] = []
        for profile_id in await self._get_index():
            profile = await self._safe_get_item(self._profile_key(profile_id))
            if profile is None:
                continue
            if profile_type and profile.get("type") != profile_type:
                continue
            if printer_id and profile.get("printer_id") != printer_id:
                continue
            profiles.append(profile)
        profiles.sort(key=lambda item: item["updated_at"], reverse=True)
        return profiles

    async def get_profile(self, profile_id: str) -> Dict[str, Any]:
        profile = await self._safe_get_item(self._profile_key(profile_id))
        if profile is None:
            raise ProfileNotFoundError(profile_id)
        return profile

    async def create_profile(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        validated = self._validate_profile_payload(payload, is_update=False)
        index = await self._get_index()
        if len(index) >= self.settings.max_profiles:
            raise ProfileValidationError(
                f"Maximum profile limit reached ({self.settings.max_profiles})"
            )

        profile_id = payload.get("id") or str(uuid4())
        if profile_id in index:
            raise ProfileValidationError("Profile with the same id already exists")

        now = _utc_iso_now()
        profile = {
            "id": profile_id,
            **validated,
            "created_at": now,
            "updated_at": now,
        }

        index.append(profile_id)
        await self._set_item(self._profile_key(profile_id), profile)
        await self._set_item("__index__", index)
        return profile

    async def update_profile(self, profile_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        profile = await self.get_profile(profile_id)
        validated = self._validate_profile_payload(payload, is_update=True)

        profile.update(validated)
        profile["updated_at"] = _utc_iso_now()
        await self._set_item(self._profile_key(profile_id), profile)
        return profile

    async def delete_profile(self, profile_id: str) -> None:
        _ = await self.get_profile(profile_id)
        index = await self._get_index()
        if profile_id in index:
            index.remove(profile_id)
            await self._set_item("__index__", index)
        await self._delete_item(self._profile_key(profile_id))

    def _validate_profile_payload(self, payload: Dict[str, Any], *, is_update: bool) -> Dict[str, Any]:
        if not isinstance(payload, dict):
            raise ProfileValidationError("Profile payload must be a JSON object")

        required_fields = ["name", "type", "payload"]
        if not is_update:
            missing = [field for field in required_fields if field not in payload]
            if missing:
                raise ProfileValidationError(f"Missing required fields: {', '.join(missing)}")

        result: Dict[str, Any] = {}

        if "name" in payload:
            name = str(payload["name"]).strip()
            if not name:
                raise ProfileValidationError("Field 'name' must be non-empty")
            result["name"] = name

        if "type" in payload:
            profile_type = str(payload["type"]).strip().lower()
            if profile_type not in _ALLOWED_PROFILE_TYPES:
                raise ProfileValidationError(
                    "Field 'type' must be one of: printer, process, filament"
                )
            result["type"] = profile_type

        if "printer_id" in payload:
            printer_id = str(payload["printer_id"]).strip()
            if not printer_id:
                raise ProfileValidationError("Field 'printer_id' must be non-empty when set")
            result["printer_id"] = printer_id

        for optional_field in ("source", "slicer", "version"):
            if optional_field in payload:
                value = str(payload[optional_field]).strip()
                if value:
                    result[optional_field] = value

        if "payload" in payload:
            profile_payload = payload["payload"]
            try:
                payload_bytes = len(json.dumps(profile_payload, separators=(",", ":")).encode("utf-8"))
            except (TypeError, ValueError) as exc:
                raise ProfileValidationError("Field 'payload' must be JSON serializable") from exc

            if payload_bytes > self.settings.max_payload_bytes:
                raise ProfileValidationError(
                    f"Field 'payload' exceeds max size of {self.settings.max_payload_bytes} bytes"
                )
            result["payload"] = profile_payload

        if is_update and not result:
            raise ProfileValidationError("No updatable profile fields were provided")

        return result

    async def _get_index(self) -> List[str]:
        index = await self._safe_get_item("__index__")
        if not isinstance(index, list):
            return []
        return [str(item) for item in index]

    def _profile_key(self, profile_id: str) -> str:
        return f"profile:{profile_id}"

    async def _safe_get_item(self, key: str) -> Any:
        try:
            return await self._get_item(key)
        except KeyError:
            return None

    async def _get_item(self, key: str) -> Any:
        getter = getattr(self.db, "get_item", None)
        if getter is None:
            raise RuntimeError("Moonraker database component does not provide get_item")
        try:
            result = getter(self.settings.namespace, key)
        except TypeError:
            result = getter(namespace=self.settings.namespace, key=key)
        if hasattr(result, "__await__"):
            return await result
        return result

    async def _set_item(self, key: str, value: Any) -> None:
        setter = getattr(self.db, "insert_item", None) or getattr(self.db, "update_item", None)
        if setter is None:
            raise RuntimeError("Moonraker database component does not provide insert/update item")
        try:
            result = setter(self.settings.namespace, key, value)
        except TypeError:
            result = setter(namespace=self.settings.namespace, key=key, value=value)
        if hasattr(result, "__await__"):
            await result

    async def _delete_item(self, key: str) -> None:
        deleter = getattr(self.db, "delete_item", None)
        if deleter is None:
            raise RuntimeError("Moonraker database component does not provide delete_item")
        try:
            result = deleter(self.settings.namespace, key)
        except TypeError:
            result = deleter(namespace=self.settings.namespace, key=key)
        if hasattr(result, "__await__"):
            await result


class InMemoryNamespaceDB:
    def __init__(self):
        self._namespaces: Dict[str, Dict[str, Any]] = {}

    def register_local_namespace(self, namespace: str) -> None:
        self._namespaces.setdefault(namespace, {})

    def get_item(self, namespace: str, key: str) -> Any:
        try:
            return self._namespaces[namespace][key]
        except KeyError as exc:
            raise KeyError(key) from exc

    def insert_item(self, namespace: str, key: str, value: Any) -> None:
        self._namespaces.setdefault(namespace, {})[key] = value

    def update_item(self, namespace: str, key: str, value: Any) -> None:
        self.insert_item(namespace, key, value)

    def delete_item(self, namespace: str, key: str) -> None:
        self._namespaces.setdefault(namespace, {}).pop(key, None)


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()
