import ipaddress
import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import get_db
from models import IPAddress, Subnet, _int_to_hex

router = APIRouter(prefix="/ip-addresses", tags=["ip-addresses"])

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
    address: str
    subnet_id: int
    dns_name: str | None = None
    description: str | None = None

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
    dns_name: str | None = None
    description: str | None = None

    @field_validator("dns_name")
    @classmethod
    def validate_dns_name(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_dns_name(v)
        return v


class IPAddressResponse(BaseModel):
    id: int
    address: str
    subnet_id: int
    is_ipv6: bool
    dns_name: str | None
    description: str | None

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


@router.get("/", response_model=list[IPAddressResponse])
async def list_ip_addresses(
    subnet_id: int | None = Query(None, description="Filter by subnet ID"),
    db: Session = Depends(get_db),
):
    query = db.query(IPAddress)
    if subnet_id is not None:
        query = query.filter(IPAddress.subnet_id == subnet_id)
    return [_ip_to_response(ip) for ip in query.all()]


@router.get("/{ip_address_id}", response_model=IPAddressResponse)
async def get_ip_address(ip_address_id: int, db: Session = Depends(get_db)):
    ip = db.query(IPAddress).filter(IPAddress.id == ip_address_id).first()
    if not ip:
        raise HTTPException(status_code=404, detail="IP address not found")
    return _ip_to_response(ip)


@router.post("/", response_model=IPAddressResponse, status_code=201)
async def create_ip_address(body: IPAddressCreate, db: Session = Depends(get_db)):
    subnet = db.query(Subnet).filter(Subnet.id == body.subnet_id).first()
    if not subnet:
        raise HTTPException(status_code=404, detail="Parent subnet not found")

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


@router.put("/{ip_address_id}", response_model=IPAddressResponse)
async def update_ip_address(
    ip_address_id: int,
    body: IPAddressUpdate,
    db: Session = Depends(get_db),
):
    ip = db.query(IPAddress).filter(IPAddress.id == ip_address_id).first()
    if not ip:
        raise HTTPException(status_code=404, detail="IP address not found")

    ip.dns_name = body.dns_name
    ip.description = body.description
    db.commit()
    db.refresh(ip)
    return _ip_to_response(ip)


@router.delete("/{ip_address_id}", status_code=204)
async def delete_ip_address(ip_address_id: int, db: Session = Depends(get_db)):
    ip = db.query(IPAddress).filter(IPAddress.id == ip_address_id).first()
    if not ip:
        raise HTTPException(status_code=404, detail="IP address not found")

    db.delete(ip)
    db.commit()