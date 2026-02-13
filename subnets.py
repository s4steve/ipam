import ipaddress

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator
from sqlalchemy.orm import Session

from database import get_db
from models import Subnet, _int_to_hex

router = APIRouter(prefix="/subnets", tags=["subnets"])


class SubnetCreate(BaseModel):
    cidr: str
    description: str | None = None

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
    id: int
    cidr: str
    netmask: str
    broadcast: str
    total_hosts: int
    usable_hosts: int
    first_usable: str
    last_usable: str
    is_ipv6: bool
    description: str | None

    model_config = {"from_attributes": True}


def _subnet_to_response(subnet: Subnet) -> SubnetResponse:
    return SubnetResponse(
        id=subnet.id,
        cidr=subnet.network_str,
        netmask=subnet.netmask,
        broadcast=subnet.broadcast_address,
        total_hosts=subnet.total_hosts,
        usable_hosts=subnet.usable_hosts,
        first_usable=subnet.first_usable,
        last_usable=subnet.last_usable,
        is_ipv6=subnet.is_ipv6,
        description=subnet.description,
    )


@router.post("/", response_model=SubnetResponse, status_code=201)
async def create_subnet(body: SubnetCreate, db: Session = Depends(get_db)):
    network = ipaddress.ip_network(body.cidr, strict=False)

    existing = db.query(Subnet).filter(
        Subnet.network_address == _int_to_hex(int(network.network_address)),
        Subnet.prefix_length == network.prefixlen,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"Subnet {body.cidr} already exists")

    subnet = Subnet.from_cidr(body.cidr, body.description)
    db.add(subnet)
    db.commit()
    db.refresh(subnet)
    return _subnet_to_response(subnet)
