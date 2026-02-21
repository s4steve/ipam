import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from database import get_db
from models import DNSZone

router = APIRouter(prefix="/dns-zones", tags=["dns-zones"])

_DNS_LABEL_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")


def _validate_zone_name(name: str) -> str:
    """Validate a DNS zone name (e.g. 'example.com.')."""
    if len(name) > 253:
        raise ValueError("Zone name must be 253 characters or fewer")
    # Strip optional trailing dot for validation, but preserve it
    labels = name.rstrip(".").split(".")
    if len(labels) < 2:
        raise ValueError(
            "Zone name must have at least two labels (e.g. example.com)"
        )
    for label in labels:
        if not _DNS_LABEL_RE.match(label):
            raise ValueError(
                f"Invalid DNS label '{label}': labels must be 1-63 characters, "
                "alphanumeric and hyphens only, and cannot start or end with a hyphen"
            )
    return name


def _validate_dns_hostname(value: str, field_name: str) -> str:
    """Validate a DNS hostname used in SOA fields (mname/rname)."""
    if len(value) > 253:
        raise ValueError(f"{field_name} must be 253 characters or fewer")
    labels = value.rstrip(".").split(".")
    if len(labels) < 2:
        raise ValueError(
            f"{field_name} must be a fully qualified domain name with at least two labels"
        )
    for label in labels:
        if not _DNS_LABEL_RE.match(label):
            raise ValueError(
                f"Invalid DNS label '{label}' in {field_name}: labels must be 1-63 "
                "characters, alphanumeric and hyphens only, and cannot start or end "
                "with a hyphen"
            )
    return value


# -- Schemas ------------------------------------------------------------------


class SOAFields(BaseModel):
    mname: str = Field(description="Primary nameserver hostname (MNAME) for this zone")
    rname: str = Field(description="Responsible party email encoded as a hostname (RNAME), e.g. hostmaster.example.com")
    serial: int = Field(1, description="Zone serial number (0–4294967295); increment after each zone change")
    refresh: int = Field(3600, description="Seconds between secondary nameserver refresh attempts")
    retry: int = Field(600, description="Seconds a secondary waits before retrying a failed refresh")
    expire: int = Field(604800, description="Seconds after which a secondary stops serving the zone if it cannot refresh")
    minimum: int = Field(86400, description="Default TTL for negative responses (NXDOMAIN) in seconds")

    @field_validator("mname")
    @classmethod
    def validate_mname(cls, v: str) -> str:
        return _validate_dns_hostname(v, "mname")

    @field_validator("rname")
    @classmethod
    def validate_rname(cls, v: str) -> str:
        return _validate_dns_hostname(v, "rname")

    @field_validator("serial")
    @classmethod
    def validate_serial(cls, v: int) -> int:
        if v < 0 or v > 4294967295:
            raise ValueError("serial must be between 0 and 4294967295")
        return v

    @field_validator("refresh", "retry", "expire", "minimum")
    @classmethod
    def validate_positive_int(cls, v: int) -> int:
        if v < 1:
            raise ValueError("Value must be a positive integer")
        return v


class DNSZoneCreate(BaseModel):
    name: str = Field(description="DNS zone name, e.g. example.com or example.com.")
    description: str | None = Field(None, description="Optional free-text description")
    soa: SOAFields = Field(description="Start of Authority record fields")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        return _validate_zone_name(v)


class DNSZoneUpdate(BaseModel):
    name: str | None = Field(None, description="New zone name; must be unique across all zones")
    description: str | None = Field(None, description="Updated description; pass null to clear")
    soa: SOAFields | None = Field(None, description="Updated SOA fields; all SOA fields must be provided when updating")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str | None) -> str | None:
        if v is not None:
            return _validate_zone_name(v)
        return v


class SOAResponse(BaseModel):
    mname: str = Field(description="Primary nameserver hostname")
    rname: str = Field(description="Responsible party email as a hostname")
    serial: int = Field(description="Zone serial number")
    refresh: int = Field(description="Refresh interval in seconds")
    retry: int = Field(description="Retry interval in seconds")
    expire: int = Field(description="Expire interval in seconds")
    minimum: int = Field(description="Negative caching TTL in seconds")


class DNSZoneResponse(BaseModel):
    id: int = Field(description="Unique DNS zone ID")
    name: str = Field(description="DNS zone name")
    description: str | None = Field(description="Optional description")
    soa: SOAResponse = Field(description="Start of Authority record")

    model_config = {"from_attributes": True}


def _zone_to_response(zone: DNSZone) -> DNSZoneResponse:
    return DNSZoneResponse(
        id=zone.id,
        name=zone.name,
        description=zone.description,
        soa=SOAResponse(
            mname=zone.soa_mname,
            rname=zone.soa_rname,
            serial=zone.soa_serial,
            refresh=zone.soa_refresh,
            retry=zone.soa_retry,
            expire=zone.soa_expire,
            minimum=zone.soa_minimum,
        ),
    )


# -- Routes -------------------------------------------------------------------


@router.get(
    "/",
    response_model=list[DNSZoneResponse],
    summary="List DNS zones",
    description="Return DNS zones, optionally filtered by exact name. Supports pagination.",
)
async def list_dns_zones(
    name: str | None = Query(None, description="Filter by exact zone name, e.g. example.com"),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip for pagination"),
    db: Session = Depends(get_db),
):
    query = db.query(DNSZone)
    if name is not None:
        query = query.filter(DNSZone.name == name)
    zones = query.offset(offset).limit(limit).all()
    return [_zone_to_response(z) for z in zones]


@router.get(
    "/{zone_id}",
    response_model=DNSZoneResponse,
    summary="Get DNS zone by ID",
)
async def get_dns_zone(zone_id: int, db: Session = Depends(get_db)):
    zone = db.query(DNSZone).filter(DNSZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="DNS zone not found")
    return _zone_to_response(zone)


@router.post(
    "/",
    response_model=DNSZoneResponse,
    status_code=201,
    summary="Create a DNS zone",
)
async def create_dns_zone(body: DNSZoneCreate, db: Session = Depends(get_db)):
    existing = db.query(DNSZone).filter(DNSZone.name == body.name).first()
    if existing:
        raise HTTPException(
            status_code=409, detail=f"DNS zone '{body.name}' already exists"
        )

    zone = DNSZone(
        name=body.name,
        description=body.description,
        soa_mname=body.soa.mname,
        soa_rname=body.soa.rname,
        soa_serial=body.soa.serial,
        soa_refresh=body.soa.refresh,
        soa_retry=body.soa.retry,
        soa_expire=body.soa.expire,
        soa_minimum=body.soa.minimum,
    )
    db.add(zone)
    db.commit()
    db.refresh(zone)
    return _zone_to_response(zone)


@router.put(
    "/{zone_id}",
    response_model=DNSZoneResponse,
    summary="Update a DNS zone",
    description="Partially update a DNS zone. Only provided fields are changed.",
)
async def update_dns_zone(
    zone_id: int,
    body: DNSZoneUpdate,
    db: Session = Depends(get_db),
):
    zone = db.query(DNSZone).filter(DNSZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="DNS zone not found")

    if body.name is not None:
        # Check uniqueness if renaming
        if body.name != zone.name:
            conflict = db.query(DNSZone).filter(DNSZone.name == body.name).first()
            if conflict:
                raise HTTPException(
                    status_code=409,
                    detail=f"DNS zone '{body.name}' already exists",
                )
        zone.name = body.name

    if body.description is not None:
        zone.description = body.description

    if body.soa is not None:
        zone.soa_mname = body.soa.mname
        zone.soa_rname = body.soa.rname
        zone.soa_serial = body.soa.serial
        zone.soa_refresh = body.soa.refresh
        zone.soa_retry = body.soa.retry
        zone.soa_expire = body.soa.expire
        zone.soa_minimum = body.soa.minimum

    db.commit()
    db.refresh(zone)
    return _zone_to_response(zone)


@router.delete(
    "/{zone_id}",
    status_code=204,
    summary="Delete a DNS zone",
    description="Delete a DNS zone. Any IP addresses whose dns_name falls within this zone are not automatically updated.",
)
async def delete_dns_zone(zone_id: int, db: Session = Depends(get_db)):
    zone = db.query(DNSZone).filter(DNSZone.id == zone_id).first()
    if not zone:
        raise HTTPException(status_code=404, detail="DNS zone not found")

    db.delete(zone)
    db.commit()
