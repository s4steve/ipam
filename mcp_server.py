"""MCP server for the IPAM REST API.

Translates LLM tool calls into HTTP requests against the running IPAM API.
Configure the API base URL via the IPAM_BASE_URL environment variable
(default: http://localhost:8000).

Run with:
    python mcp_server.py          # stdio transport (Claude Desktop)
    python -m mcp dev mcp_server.py  # MCP Inspector (browser UI)
"""

import os
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("IPAM_BASE_URL", "http://localhost:8000").rstrip("/")


@asynccontextmanager
async def lifespan(server):
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=30.0) as client:
        yield {"client": client}


mcp = FastMCP(
    "IPAM",
    lifespan=lifespan,
    instructions=(
        "Tools for managing an IP Address Management (IPAM) system. "
        "Supports subnets, IP address allocation, and DNS zones. "
        "The IPAM API must be running at the configured base URL before calling any tool."
    ),
)


async def _request(
    method: str,
    path: str,
    *,
    params: Optional[dict] = None,
    body: Optional[dict] = None,
) -> str:
    ctx = mcp.get_context()
    client: httpx.AsyncClient = ctx.request_context.lifespan_context["client"]

    clean_params = {k: v for k, v in (params or {}).items() if v is not None} or None

    try:
        response = await client.request(method, path, params=clean_params, json=body)
    except httpx.ConnectError as exc:
        return f"Connection error: {exc}. Is the IPAM API running at {BASE_URL}?"
    except httpx.TimeoutException as exc:
        return f"Timeout: {exc}"

    if response.status_code == 204:
        return "Deleted successfully."

    if response.is_error:
        try:
            detail = response.json().get("detail", response.text)
        except Exception:
            detail = response.text
        return f"Error {response.status_code}: {detail}"

    return response.text


# ---------------------------------------------------------------------------
# Subnet tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_subnets(
    cidr: Optional[str] = None,
    name: Optional[str] = None,
    contains: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """List subnets, optionally filtered.

    Args:
        cidr: Filter by exact CIDR notation (e.g. "10.0.0.0/8").
        name: Filter by subnet name (case-insensitive substring match).
        contains: Filter to subnets that contain this IP address.
        limit: Maximum number of results to return (default 100).
        offset: Number of results to skip for pagination (default 0).
    """
    return await _request(
        "GET",
        "/subnets/",
        params={"cidr": cidr, "name": name, "contains": contains, "limit": limit, "offset": offset},
    )


@mcp.tool()
async def get_subnet(subnet_id: int) -> str:
    """Get a single subnet by ID.

    Args:
        subnet_id: The numeric ID of the subnet.
    """
    return await _request("GET", f"/subnets/{subnet_id}")


@mcp.tool()
async def create_subnet(
    name: str,
    cidr: str,
    description: Optional[str] = None,
) -> str:
    """Create a new subnet.

    Args:
        name: Human-readable name for the subnet.
        cidr: Network in CIDR notation (e.g. "192.168.1.0/24").
        description: Optional free-text description.
    """
    body: dict[str, Any] = {"name": name, "cidr": cidr}
    if description is not None:
        body["description"] = description
    return await _request("POST", "/subnets/", body=body)


@mcp.tool()
async def allocate_next_ip(
    subnet_id: int,
    dns_name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """Allocate the next free IP address in a subnet.

    The lowest unallocated host address is assigned automatically.

    Args:
        subnet_id: The numeric ID of the subnet to allocate from.
        dns_name: Optional DNS name to assign to the new IP address.
        description: Optional free-text description for the new IP address.
    """
    body: dict[str, Any] = {}
    if dns_name is not None:
        body["dns_name"] = dns_name
    if description is not None:
        body["description"] = description
    return await _request("POST", f"/subnets/{subnet_id}/allocate", body=body or None)


# ---------------------------------------------------------------------------
# IP Address tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_ip_addresses(
    subnet_id: Optional[int] = None,
    address: Optional[str] = None,
    dns_name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """List IP addresses, optionally filtered.

    Args:
        subnet_id: Filter to addresses within this subnet ID.
        address: Filter by exact IP address (e.g. "10.0.0.1").
        dns_name: Filter by DNS name (case-insensitive substring match).
        limit: Maximum number of results to return (default 100).
        offset: Number of results to skip for pagination (default 0).
    """
    return await _request(
        "GET",
        "/ip-addresses/",
        params={
            "subnet_id": subnet_id,
            "address": address,
            "dns_name": dns_name,
            "limit": limit,
            "offset": offset,
        },
    )


@mcp.tool()
async def get_ip_address(ip_address_id: int) -> str:
    """Get a single IP address record by ID.

    Args:
        ip_address_id: The numeric ID of the IP address record.
    """
    return await _request("GET", f"/ip-addresses/{ip_address_id}")


@mcp.tool()
async def create_ip_address(
    address: str,
    subnet_id: int,
    dns_name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """Create (register) a specific IP address in a subnet.

    Use allocate_next_ip instead if you want automatic address selection.

    Args:
        address: The IP address to register (e.g. "192.168.1.10").
        subnet_id: The numeric ID of the subnet this address belongs to.
        dns_name: Optional DNS name to assign to this address.
        description: Optional free-text description.
    """
    body: dict[str, Any] = {"address": address, "subnet_id": subnet_id}
    if dns_name is not None:
        body["dns_name"] = dns_name
    if description is not None:
        body["description"] = description
    return await _request("POST", "/ip-addresses/", body=body)


@mcp.tool()
async def update_ip_address(
    ip_address_id: int,
    dns_name: Optional[str] = None,
    description: Optional[str] = None,
) -> str:
    """Update the DNS name and/or description of an IP address record.

    Only the fields you provide are changed.

    Args:
        ip_address_id: The numeric ID of the IP address record to update.
        dns_name: New DNS name (pass an empty string to clear it).
        description: New description (pass an empty string to clear it).
    """
    body: dict[str, Any] = {}
    if dns_name is not None:
        body["dns_name"] = dns_name
    if description is not None:
        body["description"] = description
    return await _request("PUT", f"/ip-addresses/{ip_address_id}", body=body)


@mcp.tool()
async def delete_ip_address(ip_address_id: int) -> str:
    """Delete an IP address record, freeing that address for reuse.

    Args:
        ip_address_id: The numeric ID of the IP address record to delete.
    """
    return await _request("DELETE", f"/ip-addresses/{ip_address_id}")


# ---------------------------------------------------------------------------
# DNS Zone tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def list_dns_zones(
    name: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
) -> str:
    """List DNS zones, optionally filtered by name.

    Args:
        name: Filter by zone name (case-insensitive substring match).
        limit: Maximum number of results to return (default 100).
        offset: Number of results to skip for pagination (default 0).
    """
    return await _request(
        "GET",
        "/dns-zones/",
        params={"name": name, "limit": limit, "offset": offset},
    )


@mcp.tool()
async def get_dns_zone(zone_id: int) -> str:
    """Get a single DNS zone by ID.

    Args:
        zone_id: The numeric ID of the DNS zone.
    """
    return await _request("GET", f"/dns-zones/{zone_id}")


@mcp.tool()
async def create_dns_zone(
    name: str,
    mname: str,
    rname: str,
    description: Optional[str] = None,
    serial: Optional[int] = None,
    refresh: Optional[int] = None,
    retry: Optional[int] = None,
    expire: Optional[int] = None,
    minimum: Optional[int] = None,
) -> str:
    """Create a new DNS zone with SOA record.

    Args:
        name: Zone name (e.g. "example.com").
        mname: Primary nameserver hostname for the SOA record (e.g. "ns1.example.com").
        rname: Responsible party email in DNS format for the SOA record (e.g. "hostmaster.example.com").
        description: Optional free-text description.
        serial: SOA serial number (defaults to current date in YYYYMMDD01 format if omitted).
        refresh: SOA refresh interval in seconds (default: 3600).
        retry: SOA retry interval in seconds (default: 900).
        expire: SOA expire interval in seconds (default: 604800).
        minimum: SOA minimum TTL in seconds (default: 300).
    """
    soa: dict[str, Any] = {"mname": mname, "rname": rname}
    if serial is not None:
        soa["serial"] = serial
    if refresh is not None:
        soa["refresh"] = refresh
    if retry is not None:
        soa["retry"] = retry
    if expire is not None:
        soa["expire"] = expire
    if minimum is not None:
        soa["minimum"] = minimum

    body: dict[str, Any] = {"name": name, "soa": soa}
    if description is not None:
        body["description"] = description

    return await _request("POST", "/dns-zones/", body=body)


@mcp.tool()
async def update_dns_zone(
    zone_id: int,
    name: Optional[str] = None,
    description: Optional[str] = None,
    mname: Optional[str] = None,
    rname: Optional[str] = None,
    serial: Optional[int] = None,
    refresh: Optional[int] = None,
    retry: Optional[int] = None,
    expire: Optional[int] = None,
    minimum: Optional[int] = None,
) -> str:
    """Update a DNS zone's name, description, and/or SOA fields.

    Only the fields you provide are changed.

    Args:
        zone_id: The numeric ID of the DNS zone to update.
        name: New zone name.
        description: New description.
        mname: New primary nameserver hostname for the SOA record.
        rname: New responsible party email (DNS format) for the SOA record.
        serial: New SOA serial number.
        refresh: New SOA refresh interval in seconds.
        retry: New SOA retry interval in seconds.
        expire: New SOA expire interval in seconds.
        minimum: New SOA minimum TTL in seconds.
    """
    body: dict[str, Any] = {}
    if name is not None:
        body["name"] = name
    if description is not None:
        body["description"] = description

    soa: dict[str, Any] = {}
    if mname is not None:
        soa["mname"] = mname
    if rname is not None:
        soa["rname"] = rname
    if serial is not None:
        soa["serial"] = serial
    if refresh is not None:
        soa["refresh"] = refresh
    if retry is not None:
        soa["retry"] = retry
    if expire is not None:
        soa["expire"] = expire
    if minimum is not None:
        soa["minimum"] = minimum

    if soa:
        body["soa"] = soa

    return await _request("PUT", f"/dns-zones/{zone_id}", body=body)


@mcp.tool()
async def delete_dns_zone(zone_id: int) -> str:
    """Delete a DNS zone.

    Args:
        zone_id: The numeric ID of the DNS zone to delete.
    """
    return await _request("DELETE", f"/dns-zones/{zone_id}")


if __name__ == "__main__":
    mcp.run(transport="stdio")
