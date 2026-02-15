# IPAM - IP Address Management

A FastAPI-based IP Address Management system for tracking subnets and IP addresses with full IPv4 and IPv6 support.

## Features

- Create and look up subnets by CIDR notation or friendly name
- Full CRUD for IP addresses with parent subnet validation
- Optional DNS name association with RFC 1123 validation
- Automatic calculation of netmask, broadcast address, usable host range, and host counts
- Full IPv4 and IPv6 support
- SQLite storage with hex-encoded addresses for correct sorting across address families

## Requirements

- Python 3.12+
- Dependencies listed in `requirements.txt`

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Running

```bash
uvicorn main:app --reload
```

The API is available at http://localhost:8000. Interactive docs are at http://localhost:8000/docs.

## API Endpoints

| Method | Path                       | Description                                |
|--------|----------------------------|--------------------------------------------|
| GET    | `/health`                  | Health check                               |
| GET    | `/subnets/`                | Look up a subnet by `cidr` or `name`       |
| POST   | `/subnets/`                | Create a new subnet                        |
| GET    | `/ip-addresses/`           | List IP addresses (optional `subnet_id` filter) |
| GET    | `/ip-addresses/{id}`       | Get a single IP address                    |
| POST   | `/ip-addresses/`           | Create an IP address                       |
| PUT    | `/ip-addresses/{id}`       | Update an IP address                       |
| DELETE | `/ip-addresses/{id}`       | Delete an IP address                       |

### Example: Create a subnet

```bash
curl -X POST http://localhost:8000/subnets/ \
  -H "Content-Type: application/json" \
  -d '{"name": "Branch Office", "cidr": "192.168.1.0/24"}'
```

### Example: Look up a subnet

```bash
curl "http://localhost:8000/subnets/?name=Branch%20Office"
curl "http://localhost:8000/subnets/?cidr=192.168.1.0/24"
```

### Example: Create an IP address

```bash
curl -X POST http://localhost:8000/ip-addresses/ \
  -H "Content-Type: application/json" \
  -d '{"address": "192.168.1.10", "subnet_id": 1, "dns_name": "server.example.com", "description": "Web server"}'
```

### Example: Update an IP address

```bash
curl -X PUT http://localhost:8000/ip-addresses/1 \
  -H "Content-Type: application/json" \
  -d '{"dns_name": "web01.example.com", "description": "Primary web server"}'
```

### Example: List IP addresses in a subnet

```bash
curl "http://localhost:8000/ip-addresses/?subnet_id=1"
```
