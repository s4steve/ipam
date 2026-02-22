# IPAM - IP Address Management

A FastAPI-based IP Address Management system for tracking subnets and IP addresses with full IPv4 and IPv6 support. Includes an MCP server so Claude Desktop (or any MCP client) can manage your IPAM directly through natural language.

## Features

- Create and look up subnets by CIDR notation or friendly name
- Full CRUD for IP addresses with parent subnet validation
- Automatic allocation of the next free IP address in a subnet
- Full CRUD for DNS zones with SOA record management
- Optional DNS name association with RFC 1123 validation, enforced to belong to an existing DNS zone
- Automatic calculation of netmask, broadcast address, usable host range, and host counts
- Full IPv4 and IPv6 support
- SQLite storage with hex-encoded addresses for correct sorting across address families
- MCP server for LLM/Claude Desktop integration

## Requirements

- Python 3.12+
- Dependencies listed in `requirements.txt`

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Authentication

All API endpoints except `/health` require a Bearer token. The token is set via the `IPAM_API_KEY` variable in a `.env` file in the project root.

### Generate an API key

Use the included `API-gen.sh` script to generate a cryptographically random 64-character hex key:

```bash
bash API-gen.sh
```

The script prints a key to stdout. Copy it into your `.env` file.

### Configure `.env`

Create `.env` in the project root (it is already listed in `.gitignore`):

```bash
IPAM_API_KEY=<paste key here>
```

Set restrictive file permissions so only your user can read it:

```bash
chmod 600 .env
```

The server loads this file automatically on startup — no additional configuration is needed.

### Using the key in requests

Pass the key as a Bearer token in the `Authorization` header:

```bash
curl -H "Authorization: Bearer $IPAM_API_KEY" http://localhost:8000/subnets/
```

You can export the key from your `.env` for use in shell commands:

```bash
export IPAM_API_KEY=<your key>
```

## Running the API

```bash
uvicorn main:app --reload
```

The API is available at http://localhost:8000. Interactive docs are at http://localhost:8000/docs.

## Docker

### Build the image

```bash
docker build -t ipam .
```

### Run with a named volume (recommended)

The SQLite database is stored in `/app/data` inside the container. Mount a volume there so data persists across container restarts:

```bash
docker run -p 8000:8000 -v ipam-data:/app/data -e IPAM_API_KEY=<your key> ipam
```

### Run with a bind mount

```bash
docker run -p 8000:8000 -v ./data:/app/data -e IPAM_API_KEY=<your key> ipam
```

### Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./ipam.db` | SQLAlchemy database URL. Set automatically to `/app/data/ipam.db` in the Docker image. |
| `IPAM_API_KEY` | *(none)* | API key required to authenticate requests. All protected endpoints return `500` if this is not set. |

## API Endpoints

| Method | Path                          | Description                                          |
|--------|-------------------------------|------------------------------------------------------|
| GET    | `/health`                     | Health check (no authentication required)            |
| GET    | `/subnets/`                   | List/filter subnets (`cidr`, `name`, `contains`)     |
| POST   | `/subnets/`                   | Create a new subnet                                  |
| GET    | `/subnets/{id}`               | Get a single subnet                                  |
| POST   | `/subnets/{id}/allocate`      | Allocate the next free IP address in a subnet        |
| GET    | `/ip-addresses/`              | List IP addresses (`subnet_id`, `address`, `dns_name`) |
| GET    | `/ip-addresses/{id}`          | Get a single IP address                              |
| POST   | `/ip-addresses/`              | Create an IP address                                 |
| PUT    | `/ip-addresses/{id}`          | Update an IP address                                 |
| DELETE | `/ip-addresses/{id}`          | Delete an IP address                                 |
| GET    | `/dns-zones/`                 | List all DNS zones                                   |
| GET    | `/dns-zones/{id}`             | Get a single DNS zone                                |
| POST   | `/dns-zones/`                 | Create a DNS zone                                    |
| PUT    | `/dns-zones/{id}`             | Update a DNS zone                                    |
| DELETE | `/dns-zones/{id}`             | Delete a DNS zone                                    |

### DNS zone validation

When creating or updating an IP address, any `dns_name` provided must be contained within an existing DNS zone. For example, if zone `example.com` exists, `host.example.com` and `sub.host.example.com` are accepted; `host.other.com` is rejected with `HTTP 400`.

### Example: Create a subnet

```bash
curl -X POST http://localhost:8000/subnets/ \
  -H "Authorization: Bearer $IPAM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name": "Branch Office", "cidr": "192.168.1.0/24"}'
```

### Example: Look up a subnet

```bash
curl -H "Authorization: Bearer $IPAM_API_KEY" "http://localhost:8000/subnets/?name=Branch%20Office"
curl -H "Authorization: Bearer $IPAM_API_KEY" "http://localhost:8000/subnets/?cidr=192.168.1.0/24"
```

### Example: Allocate the next free IP address

```bash
curl -X POST http://localhost:8000/subnets/1/allocate \
  -H "Authorization: Bearer $IPAM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"dns_name": "host1.example.com", "description": "First host"}'
```

### Example: Create an IP address

```bash
curl -X POST http://localhost:8000/ip-addresses/ \
  -H "Authorization: Bearer $IPAM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"address": "192.168.1.10", "subnet_id": 1, "dns_name": "server.example.com", "description": "Web server"}'
```

### Example: Update an IP address

```bash
curl -X PUT http://localhost:8000/ip-addresses/1 \
  -H "Authorization: Bearer $IPAM_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"dns_name": "web01.example.com", "description": "Primary web server"}'
```

### Example: List IP addresses in a subnet

```bash
curl -H "Authorization: Bearer $IPAM_API_KEY" "http://localhost:8000/ip-addresses/?subnet_id=1"
```

## MCP Server

`mcp_server.py` exposes all 14 API actions as MCP tools so Claude Desktop or any MCP client can manage your IPAM through natural language.

### Tools

| Tool | Description |
|------|-------------|
| `list_subnets` | List/filter subnets |
| `get_subnet` | Get a subnet by ID |
| `create_subnet` | Create a new subnet |
| `allocate_next_ip` | Allocate the next free IP in a subnet |
| `list_ip_addresses` | List/filter IP addresses |
| `get_ip_address` | Get an IP address by ID |
| `create_ip_address` | Register a specific IP address |
| `update_ip_address` | Update DNS name or description |
| `delete_ip_address` | Delete an IP address record |
| `list_dns_zones` | List/filter DNS zones |
| `get_dns_zone` | Get a DNS zone by ID |
| `create_dns_zone` | Create a zone with SOA record |
| `update_dns_zone` | Update zone name, description, or SOA fields |
| `delete_dns_zone` | Delete a DNS zone |

### Claude Desktop configuration

Add the following to `~/.config/Claude/claude_desktop_config.json` (Linux) or `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS):

```json
{
  "mcpServers": {
    "ipam": {
      "command": "/path/to/IPAM/.venv/bin/python",
      "args": ["/path/to/IPAM/mcp_server.py"],
      "env": {
        "IPAM_BASE_URL": "http://localhost:8000",
        "IPAM_API_KEY": "<your key>"
      }
    }
  }
}
```

### Testing with MCP Inspector

```bash
# Terminal 1 — IPAM API must be running first
uvicorn main:app --reload

# Terminal 2 — opens browser UI at http://localhost:5173
IPAM_API_KEY=<your key> python -m mcp dev mcp_server.py
```
