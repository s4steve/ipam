# IPAM - IP Address Management

A FastAPI-based IP Address Management system for tracking subnets and IP addresses with full IPv4 and IPv6 support.

## Features

- Create and look up subnets by CIDR notation or friendly name
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

| Method | Path       | Description                          |
|--------|------------|--------------------------------------|
| GET    | `/health`  | Health check                         |
| GET    | `/subnets/`| Look up a subnet by `cidr` or `name` |
| POST   | `/subnets/`| Create a new subnet                  |

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
