# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

FastAPI-based IP Address Management (IPAM) system with SQLite storage. Manages subnets and IP addresses with full IPv4/IPv6 support.

## Commands

```bash
# Run the dev server (auto-reload)
.venv/bin/uvicorn main:app --reload

# Install dependencies
.venv/bin/pip install -r requirements.txt
```

API docs available at http://localhost:8000/docs when running.

## Architecture

Single-module FastAPI app (no package structure). All source files are in the project root.

- **main.py** - App entry point, creates tables on startup via `Base.metadata.create_all()`
- **database.py** - SQLAlchemy engine, session factory, and `get_db()` dependency
- **models.py** - ORM models: `Subnet` and `IPAddress`
- **subnets.py** - `/subnets` router with Pydantic request/response schemas inline
- **health.py** - `GET /health` endpoint

### IP Address Storage Strategy

IP addresses are stored as **zero-padded 32-character hex strings** (not dotted-decimal or colon notation). This enables correct lexicographic sorting for both IPv4 and IPv6 and supports the full 128-bit range. Models provide computed properties (`network_str`, `address_str`) to convert back to standard notation, and factory methods (`Subnet.from_cidr()`, `IPAddress.from_string()`) to create instances from human-readable input.

### Database

SQLite at `./ipam.db`, auto-created on first run. No migration tool (no Alembic). Schema changes require manual DB recreation.

- `subnets` → has many `ip_addresses` (cascade delete)
- `ip_addresses` → belongs to one `subnet` (foreign key, unique address constraint)

### Patterns

- **Dependency injection**: Routes receive DB sessions via `Depends(get_db)`
- **Pydantic schemas**: Defined alongside routes in `subnets.py`, using `from_attributes=True` for ORM compatibility
- **Field validators**: CIDR input is validated and normalized to the true network address in `SubnetCreate`