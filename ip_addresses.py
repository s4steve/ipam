import ipaddress
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from database import get_db
from models import DNSZone, IPAddress, Subnet, _int_to_hex

router = APIRouter(prefix="/ip-addresses", tags=["ip-addresses"])


def _assert_dns_name_in_zone(dns_name: str, db: Session) -> None:
    """Raise 400 if dns_name is not contained within any existing DNS zone."""
    normalized = dns_name.rstrip(".")
    zones = db.query(DNSZone.name).all()
    for (zone_name,) in zones:
        zone = zone_name.rstrip(".")
        if normalized == zone or normalized.endswith("." + zone):
            return
    raise HTTPException(
        status_code=400,
        detail=f"DNS name '{dns_name}' does not belong to any existing DNS zone",
    )


_DNS_LABEL_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")


def _validate_dns_name(name: str) -> str:
    if len(name) > 253:
        raise ValueError("DNS name must be 253 characters or fewer")
    labels = name.rstrip(".").split(".")
    if len(labels) < 2:
        raise ValueError("DNS name must have at least two labels (e.g. host.example.com)")
    for label in labels:
        if not _DNS_LABEL_RE.match(label):
            raise ValueError(
                f"Invalid DNS label '{label}': labels must be 1-63 characters, "
                "alphanumeric and hyphens only, and cannot start or end with a hyphen"
            )
    return name


# -- Schemas ------------------------------------------------------------------


class IPAddressCreate(BaseModel):
    address: str = Field(description="IP address in standard dotted-decimal (IPv4) or colon (IPv6) notation")
    subnet_id: int = Field(description="ID of the parent subnet; the address must fall within that subnet's range")
    dns_name: str | None = Field(
        None,
        description="Fully-qualified DNS name to associate with this address; must belong to an existing DNS zone",
    )
    description: str | None = Field(None, description="Optional free-text description")

    @field_validator("address")
    @classmethod
    def validate_address(cls, v: str) -> str:
        try:
            ipaddress.ip_address(v)
        except ValueError:
            raise ValueError("Invalid IP address")
        return v

    @field_validator("dns_name")
    @classmethod
    def validate_dns_name(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_dns_name(v)
        return v


class IPAddressUpdate(BaseModel):
    dns_name: str | None = Field(
        None,
        description="Fully-qualified DNS name to associate with this address; must belong to an existing DNS zone. Pass null to clear.",
    )
    description: str | None = Field(None, description="Optional free-text description. Pass null to clear.")

    @field_validator("dns_name")
    @classmethod
    def validate_dns_name(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_dns_name(v)
        return v


class IPAddressResponse(BaseModel):
    id: int = Field(description="Unique IP address record ID")
    address: str = Field(description="IP address in standard dotted-decimal or colon notation")
    subnet_id: int = Field(description="ID of the parent subnet")
    is_ipv6: bool = Field(description="True if this is an IPv6 address")
    dns_name: str | None = Field(description="Associated DNS name, if any")
    description: str | None = Field(description="Optional description")

    model_config = {"from_attributes": True}


def _ip_to_response(ip: IPAddress) -> IPAddressResponse:
    return IPAddressResponse(
        id=ip.id,
        address=ip.address_str,
        subnet_id=ip.subnet_id,
        is_ipv6=ip.is_ipv6,
        dns_name=ip.dns_name,
        description=ip.description,
    )


# -- Routes -------------------------------------------------------------------


@router.get(
    "/",
    response_model=list[IPAddressResponse],
    summary="List IP addresses",
    description="Return IP addresses, optionally filtered by subnet, exact address, or DNS name. Supports pagination.",
)
async def list_ip_addresses(
    subnet_id: int | None = Query(None, description="Filter by parent subnet ID"),
    address: str | None = Query(
        None,
        description="Filter by exact IP address in dotted-decimal or colon notation, e.g. 192.168.1.10",
    ),
    dns_name: str | None = Query(None, description="Filter by exact DNS name, e.g. host.example.com"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip for pagination"),
    db: Session = Depends(get_db),
):
    query = db.query(IPAddress)

    if subnet_id is not None:
        query = query.filter(IPAddress.subnet_id == subnet_id)

    if address is not None:
        try:
            addr = ipaddress.ip_address(address)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid IP address")
        query = query.filter(IPAddress.address == _int_to_hex(int(addr)))

    if dns_name is not None:
        query = query.filter(IPAddress.dns_name == dns_name)

    return [_ip_to_response(ip) for ip in query.offset(offset).limit(limit).all()]


@router.get(
    "/{ip_address_id}",
    response_model=IPAddressResponse,
    summary="Get IP address by ID",
)
async def get_ip_address(ip_address_id: int, db: Session = Depends(get_db)):
    ip = db.query(IPAddress).filter(IPAddress.id == ip_address_id).first()
    if not ip:
        raise HTTPException(status_code=404, detail="IP address not found")
    return _ip_to_response(ip)


@router.post(
    "/",
    response_model=IPAddressResponse,
    status_code=201,
    summary="Create an IP address",
    description="Register a specific IP address within an existing subnet, optionally associating a DNS name.",
)
async def create_ip_address(body: IPAddressCreate, db: Session = Depends(get_db)):
    subnet = db.query(Subnet).filter(Subnet.id == body.subnet_id).first()
    if not subnet:
        raise HTTPException(status_code=404, detail="Parent subnet not found")

    if body.dns_name is not None:
        _assert_dns_name_in_zone(body.dns_name, db)

    addr = ipaddress.ip_address(body.address)
    hex_addr = _int_to_hex(int(addr))

    existing = db.query(IPAddress).filter(IPAddress.address == hex_addr).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"IP address {body.address} already exists")

    try:
        ip = IPAddress.from_string(body.address, subnet, body.description, body.dns_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    db.add(ip)
    db.commit()
    db.refresh(ip)
    return _ip_to_response(ip)


@router.put(
    "/{ip_address_id}",
    response_model=IPAddressResponse,
    summary="Update an IP address",
    description="Update the DNS name and/or description of an existing IP address record.",
)
async def update_ip_address(
    ip_address_id: int,
    body: IPAddressUpdate,
    db: Session = Depends(get_db),
):
    ip = db.query(IPAddress).filter(IPAddress.id == ip_address_id).first()
    if not ip:
        raise HTTPException(status_code=404, detail="IP address not found")

    if body.dns_name is not None:
        _assert_dns_name_in_zone(body.dns_name, db)

    ip.dns_name = body.dns_name
    ip.description = body.description
    db.commit()
    db.refresh(ip)
    return _ip_to_response(ip)


@router.delete(
    "/{ip_address_id}",
    status_code=204,
    summary="Delete an IP address",
    description="Remove an IP address record, freeing it for future allocation.",
)
async def delete_ip_address(ip_address_id: int, db: Session = Depends(get_db)):
    ip = db.query(IPAddress).filter(IPAddress.id == ip_address_id).first()
    if not ip:
        raise HTTPException(status_code=404, detail="IP address not found")

    db.delete(ip)
    db.commit()
