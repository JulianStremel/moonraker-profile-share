# moonraker-profile-share

A Moonraker addon that stores and serves printer/slicer profiles using Moonraker's SQLite database namespace API.

## Features

- Stores profiles in Moonraker DB under one dedicated namespace (default: `moonraker_profile_share`)
- CRUD endpoints for profile management
- Supports profile types: `printer`, `process`, `filament`
- Optional filtering by `type` and `printer_id`
- Enforces profile count and payload size limits

## Component loading

Moonraker loads the addon via:

```python
from moonraker_profile_share import load_component
```

The component entrypoint returns `ProfileShareComponent`.

## Configuration

The addon reads these config keys:

- `enabled` (default: `true`)
- `namespace` (default: `moonraker_profile_share`)
- `max_profiles` (default: `500`)
- `max_payload_bytes` (default: `2097152`)

## API endpoints

All endpoints require Moonraker auth.

- `GET /server/profile_share/profiles`
  - Query params: `type`, `printer_id`
  - Returns `{ namespace, count, profiles }`
- `POST /server/profile_share/profiles`
  - Body fields: `name`, `type`, `payload`
  - Optional: `printer_id`, `source`, `slicer`, `version`, `id`
- `GET /server/profile_share/profiles/{profile_id}`
- `PUT /server/profile_share/profiles/{profile_id}`
  - Accepts same fields as create, all optional for partial update
- `DELETE /server/profile_share/profiles/{profile_id}`

Profile response shape:

```json
{
  "id": "<stable id>",
  "name": "ABS Draft",
  "type": "process",
  "printer_id": "voron-24",
  "source": "orca",
  "slicer": "OrcaSlicer",
  "version": "2.1",
  "created_at": "2026-05-20T12:00:00+00:00",
  "updated_at": "2026-05-20T12:00:00+00:00",
  "profile": {"...": "..."}
}
```

## Running tests

```bash
python -m unittest discover -s tests -v
```
