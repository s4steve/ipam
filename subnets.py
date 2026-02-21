import ipaddress

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import DNSZone, IPAddress, Subnet, _hex_to_int, _int_to_hex

router = APIRouter(prefix="/subnets", tags=["subnets"])


# -- Schemas ------------------------------------------------------------------


class SubnetCreate(BaseModel):
    name: str = Field(description="Human-readable name for the subnet")
    cidr: str = Field(description="Network in CIDR notation, e.g. 192.168.1.0/24 or 2001:db8::/32")
    description: str | None = Field(None, description="Optional free-text description")

    @field_validator("cidr")
    @classmethod
    def validate_cidr(cls, v: str) -> str:
        try:
            network = ipaddress.ip_network(v, strict=False)
        except ValueError:
            raise ValueError(
                "Invalid CIDR notation. Expected format: 192.168.1.0/24 (IPv4) or 2001:db8::/32 (IPv6)"
            )
        # Normalise to the true network address (e.g. 192.168.1.5/24 -> 192.168.1.0/24)
        return str(network)


class SubnetResponse(BaseModel):
    id: int = Field(description="Unique subnet ID")
    name: str = Field(description="Human-readable subnet name")
    cidr: str = Field(description="Network address in CIDR notation")
    netmask: str = Field(description="Subnet mask in dotted-decimal notation")
    broadcast: str = Field(description="Broadcast address")
    total_hosts: int = Field(description="Total number of addresses in the subnet, including network and broadcast")
    usable_hosts: int = Field(description="Number of usable host addresses (excludes network and broadcast for /30 and larger)")
    allocated_count: int = Field(description="Number of IP addresses currently allocated in this subnet")
    free_count: int = Field(description="Number of usable addresses not yet allocated")
    first_usable: str = Field(description="First usable host address")
    last_usable: str = Field(description="Last usable host address")
    is_ipv6: bool = Field(description="True if this is an IPv6 subnet")
    description: str | None = Field(description="Optional description")

    model_config = {"from_attributes": True}


class AllocateRequest(BaseModel):
    dns_name: str | None = Field(
        None,
        description="DNS name to assign to the allocated address; must belong to an existing DNS zone",
    )
    description: str | None = Field(None, description="Optional description for the allocated address")


class AllocatedIPResponse(BaseModel):
    id: int = Field(description="Unique IP address record ID")
    address: str = Field(description="Allocated IP address in standard dotted-decimal or colon notation")
    subnet_id: int = Field(description="ID of the parent subnet")
    is_ipv6: bool = Field(description="True if this is an IPv6 address")
    dns_name: str | None = Field(description="Associated DNS name, if any")
    description: str | None = Field(description="Optional description")


# -- Helpers ------------------------------------------------------------------


def _get_allocated_counts(subnet_ids: list[int], db: Session) -> dict[int, int]:
    if not subnet_ids:
        return {}
    rows = (
        db.query(IPAddress.subnet_id, func.count(IPAddress.id))
        .filter(IPAddress.subnet_id.in_(subnet_ids))
        .group_by(IPAddress.subnet_id)
        .all()
    )
    return {subnet_id: count for subnet_id, count in rows}


def _subnet_to_response(subnet: Subnet, allocated_count: int) -> SubnetResponse:
    return SubnetResponse(
        id=subnet.id,
        name=subnet.name,
        cidr=subnet.network_str,
        netmask=subnet.netmask,
        broadcast=subnet.broadcast_address,
        total_hosts=subnet.total_hosts,
        usable_hosts=subnet.usable_hosts,
        allocated_count=allocated_count,
        free_count=max(0, subnet.usable_hosts - allocated_count),
        first_usable=subnet.first_usable,
        last_usable=subnet.last_usable,
        is_ipv6=subnet.is_ipv6,
        description=subnet.description,
    )


# -- Routes -------------------------------------------------------------------


@router.get(
    "/",
    response_model=list[SubnetResponse],
    summary="List subnets",
    description=(
        "Return subnets, optionally filtered by exact CIDR, exact name, or by a contained IP address. "
        "Supports pagination via limit and offset."
    ),
)
async def list_subnets(
    cidr: str | None = Query(None, description="Filter by exact CIDR, e.g. 192.168.1.0/24"),
    name: str | None = Query(None, description="Filter by exact subnet name"),
    contains: str | None = Query(
        None,
        description="Return only the subnet(s) whose range includes this IP address, e.g. 10.0.0.5",
    ),
    limit: int = Query(100, ge=1, le=1000, description="Maximum number of results to return"),
    offset: int = Query(0, ge=0, description="Number of results to skip for pagination"),
    db: Session = Depends(get_db),
):
    query = db.query(Subnet)

    if cidr is not None:
        try:
            network = ipaddress.ip_network(cidr, strict=False)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid CIDR notation")
        query = query.filter(
            Subnet.network_address == _int_to_hex(int(network.network_address)),
            Subnet.prefix_length == network.prefixlen,
        )

    if name is not None:
        query = query.filter(Subnet.name == name)

    if contains is not None:
        try:
            target = ipaddress.ip_address(contains)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid IP address in 'contains' parameter")
        # Containment check requires inspecting each subnet's range; filter in Python
        subnets = [s for s in query.all() if target in s.network]
        subnets = subnets[offset : offset + limit]
    else:
        subnets = query.offset(offset).limit(limit).all()

    counts = _get_allocated_counts([s.id for s in subnets], db)
    return [_subnet_to_response(s, counts.get(s.id, 0)) for s in subnets]


@router.get(
    "/{subnet_id}",
    response_model=SubnetResponse,
    summary="Get subnet by ID",
)
async def get_subnet(subnet_id: int, db: Session = Depends(get_db)):
    subnet = db.query(Subnet).filter(Subnet.id == subnet_id).first()
    if not subnet:
        raise HTTPException(status_code=404, detail="Subnet not found")
    counts = _get_allocated_counts([subnet.id], db)
    return _subnet_to_response(subnet, counts.get(subnet.id, 0))


@router.post(
    "/",
    response_model=SubnetResponse,
    status_code=201,
    summary="Create a subnet",
)
async def create_subnet(body: SubnetCreate, db: Session = Depends(get_db)):
    network = ipaddress.ip_network(body.cidr, strict=False)

    existing = db.query(Subnet).filter(
        Subnet.network_address == _int_to_hex(int(network.network_address)),
        Subnet.prefix_length == network.prefixlen,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Subnet {body.cidr} already exists")

    subnet = Subnet.from_cidr(body.cidr, body.name, body.description)
    db.add(subnet)
    db.commit()
    db.refresh(subnet)
    return _subnet_to_response(subnet, 0)


@router.post(
    "/{subnet_id}/allocate",
    response_model=AllocatedIPResponse,
    status_code=201,
    summary="Allocate the next available IP in a subnet",
    description=(
        "Find the lowest unallocated usable IP address in the subnet, create a record for it, "
        "and return it. Returns 409 if the subnet is full."
    ),
)
async def allocate_next_ip(
    subnet_id: int,
    body: AllocateRequest,
    db: Session = Depends(get_db),
):
    subnet = db.query(Subnet).filter(Subnet.id == subnet_id).first()
    if not subnet:
        raise HTTPException(status_code=404, detail="Subnet not found")

    if body.dns_name is not None:
        normalized = body.dns_name.rstrip(".")
        zones = db.query(DNSZone.name).all()
        if not any(
            normalized == z.rstrip(".") or normalized.endswith("." + z.rstrip("."))
            for (z,) in zones
        ):
            raise HTTPException(
                status_code=400,
                detail=f"DNS name '{body.dns_name}' does not belong to any existing DNS zone",
            )

    network = subnet.network
    is_ipv6 = subnet.is_ipv6
    max_prefix = 128 if is_ipv6 else 32

    if network.prefixlen >= (max_prefix - 1):
        start_int = int(network.network_address)
        end_int = int(network.broadcast_address)
    else:
        start_int = int(network.network_address) + 1
        end_int = int(network.broadcast_address) - 1

    if start_int > end_int:
        raise HTTPException(status_code=409, detail="Subnet has no usable addresses")

    start_hex = _int_to_hex(start_int)
    end_hex = _int_to_hex(end_int)

    # Load allocated addresses within the usable range, sorted lexicographically.
    # Lexicographic order == numeric order for fixed-width zero-padded hex strings.
    allocated = sorted(
        row.address
        for row in db.query(IPAddress.address)
        .filter(
            IPAddress.subnet_id == subnet_id,
            IPAddress.address >= start_hex,
            IPAddress.address <= end_hex,
        )
        .all()
    )

    # Walk the sorted list to find the first gap from start_hex
    candidate_hex = start_hex
    for hex_addr in allocated:
        if hex_addr > candidate_hex:
            break  # gap found before this address
        # hex_addr == candidate_hex; advance to next candidate
        candidate_hex = _int_to_hex(_hex_to_int(candidate_hex) + 1)

    if candidate_hex > end_hex:
        raise HTTPException(status_code=409, detail="No free IP addresses available in this subnet")

    ip = IPAddress(
        address=candidate_hex,
        is_ipv6=is_ipv6,
        dns_name=body.dns_name,
        description=body.description,
        subnet_id=subnet_id,
    )
    db.add(ip)
    db.commit()
    db.refresh(ip)

    return AllocatedIPResponse(
        id=ip.id,
        address=ip.address_str,
        subnet_id=ip.subnet_id,
        is_ipv6=ip.is_ipv6,
        dns_name=ip.dns_name,
        description=ip.description,
    )
