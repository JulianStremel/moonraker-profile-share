import asyncio
import unittest

from moonraker_profile_share.component import ProfileShareComponent
from moonraker_profile_share.store import (
    InMemoryNamespaceDB,
    NamespaceProfileStore,
    ProfileNotFoundError,
    ProfileValidationError,
    StoreSettings,
)


class FakeServer:
    def __init__(self):
        self.db = InMemoryNamespaceDB()
        self.endpoints = []

    def lookup_component(self, name):
        if name in {"database", "db"}:
            return self.db
        raise KeyError(name)

    def register_endpoint(self, path, methods, handler, auth_required=True):
        self.endpoints.append((path, tuple(methods), handler, auth_required))

    def error(self, msg):
        return ValueError(msg)


class FakeConfig:
    def __init__(self, server, values=None):
        self.server = server
        self.values = values or {}

    def get_server(self):
        return self.server

    def get(self, key, default=None):
        return self.values.get(key, default)


class NamespaceProfileStoreTests(unittest.TestCase):
    def test_crud_flow_and_filters(self):
        async def run():
            store = NamespaceProfileStore(
                InMemoryNamespaceDB(),
                StoreSettings(namespace="ns", max_profiles=5, max_payload_bytes=1024),
            )
            await store.initialize()

            created = await store.create_profile(
                {
                    "name": "PLA Draft",
                    "type": "process",
                    "printer_id": "voron-24",
                    "payload": {"layer_height": 0.2},
                }
            )
            self.assertEqual(created["type"], "process")

            fetched = await store.get_profile(created["id"])
            self.assertEqual(fetched["name"], "PLA Draft")

            updated = await store.update_profile(
                created["id"], {"name": "PLA Quality", "payload": {"layer_height": 0.12}}
            )
            self.assertEqual(updated["name"], "PLA Quality")

            listed = await store.list_profiles(profile_type="process", printer_id="voron-24")
            self.assertEqual(len(listed), 1)

            await store.delete_profile(created["id"])
            with self.assertRaises(ProfileNotFoundError):
                await store.get_profile(created["id"])

        asyncio.run(run())

    def test_validation_errors(self):
        async def run():
            store = NamespaceProfileStore(
                InMemoryNamespaceDB(),
                StoreSettings(namespace="ns", max_profiles=1, max_payload_bytes=16),
            )
            await store.initialize()

            with self.assertRaises(ProfileValidationError):
                await store.create_profile({"name": "x", "type": "bad", "payload": {}})

            await store.create_profile({"name": "ok", "type": "printer", "payload": {"a": 1}})

            with self.assertRaises(ProfileValidationError):
                await store.create_profile({"name": "overflow", "type": "printer", "payload": {"a": 2}})

            with self.assertRaises(ProfileNotFoundError):
                await store.update_profile("missing", {"name": "noop"})

        asyncio.run(run())


class ComponentTests(unittest.TestCase):
    def test_component_registers_endpoints_and_handles_crud(self):
        async def run():
            server = FakeServer()
            config = FakeConfig(server, {"namespace": "moonraker_profile_share"})
            component = ProfileShareComponent(config)
            await component.component_init()
            self.assertEqual(len(server.endpoints), 5)

            created = await component._handle_create_profile(
                {
                    "name": "Printer Profile",
                    "type": "printer",
                    "printer_id": "sv06",
                    "payload": {"bed": "220x220"},
                }
            )
            self.assertEqual(created["name"], "Printer Profile")

            listed = await component._handle_list_profiles({"type": "printer"})
            self.assertEqual(listed["count"], 1)

            profile_id = created["id"]
            fetched = await component._handle_get_profile({"profile_id": profile_id})
            self.assertEqual(fetched["id"], profile_id)

            updated = await component._handle_update_profile(
                {"profile_id": profile_id, "name": "Printer Profile v2", "payload": {"bed": "300x300"}}
            )
            self.assertEqual(updated["name"], "Printer Profile v2")

            deleted = await component._handle_delete_profile({"profile_id": profile_id})
            self.assertEqual(deleted["deleted"], profile_id)

            with self.assertRaises(ValueError):
                await component._handle_get_profile({"profile_id": profile_id})

        asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
