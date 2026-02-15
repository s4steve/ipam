import ipaddress

from sqlalchemy import Boolean, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base

# Addresses are stored as zero-padded hex strings so they sort correctly
# and support the full 128-bit range needed for IPv6.
# IPv4 example:  "000000000a000001"  (10.0.0.1)
# IPv6 example:  "20010db8000000000000000000000001"
_HEX_LEN = 32  # 128 bits / 4 bits per hex char


def _int_to_hex(value: int) -> str:
    return format(value, f"0{_HEX_LEN}x")


def _hex_to_int(value: str) -> int:
    return int(value, 16)


class Subnet(Base):
    __tablename__ = "subnets"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String, nullable=False)
    network_address: Mapped[str] = mapped_column(String(32), nullable=False)
    prefix_length: Mapped[int] = mapped_column(Integer, nullable=False)
    is_ipv6: Mapped[bool] = mapped_column(Boolean, default=False)
    description: Mapped[str | None] = mapped_column(String, nullable=True)

    ip_addresses: Mapped[list["IPAddress"]] = relationship(
        back_populates="subnet", cascade="all, delete-orphan"
    )

    @property
    def network(self) -> ipaddress.IPv4Network | ipaddress.IPv6Network:
        addr_int = _hex_to_int(self.network_address)
        if self.is_ipv6:
            return ipaddress.IPv6Network((addr_int, self.prefix_length), strict=False)
        return ipaddress.IPv4Network((addr_int, self.prefix_length), strict=False)

    @property
    def network_str(self) -> str:
        return str(self.network)

    @property
    def netmask(self) -> str:
        return str(self.network.netmask)

    @property
    def broadcast_address(self) -> str:
        return str(self.network.broadcast_address)

    @property
    def total_hosts(self) -> int:
        return self.network.num_addresses

    @property
    def usable_hosts(self) -> int:
        if self.prefix_length >= (128 if self.is_ipv6 else 31):
            return self.total_hosts
        return self.total_hosts - 2

    @property
    def first_usable(self) -> str:
        if self.prefix_length >= (128 if self.is_ipv6 else 31):
            return str(self.network.network_address)
        return str(self.network.network_address + 1)

    @property
    def last_usable(self) -> str:
        if self.prefix_length >= (128 if self.is_ipv6 else 31):
            return str(self.network.broadcast_address)
        return str(self.network.broadcast_address - 1)

    def contains(self, address: str) -> bool:
        return ipaddress.ip_address(address) in self.network

    @classmethod
    def from_cidr(cls, cidr: str, name: str, description: str | None = None) -> "Subnet":
        network = ipaddress.ip_network(cidr, strict=False)
        return cls(
            name=name,
            network_address=_int_to_hex(int(network.network_address)),
            prefix_length=network.prefixlen,
            is_ipv6=isinstance(network, ipaddress.IPv6Network),
            description=description,
        )


class IPAddress(Base):
    __tablename__ = "ip_addresses"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    address: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    is_ipv6: Mapped[bool] = mapped_column(Boolean, default=False)
    dns_name: Mapped[str | None] = mapped_column(String(253), nullable=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    subnet_id: Mapped[int] = mapped_column(ForeignKey("subnets.id"), nullable=False)

    subnet: Mapped[Subnet] = relationship(back_populates="ip_addresses")

    @property
    def _addr_int(self) -> int:
        return _hex_to_int(self.address)

    @property
    def address_str(self) -> str:
        if self.is_ipv6:
            return str(ipaddress.IPv6Address(self._addr_int))
        return str(ipaddress.IPv4Address(self._addr_int))

    def offset(self, value: int) -> str:
        new_int = self._addr_int + value
        if self.is_ipv6:
            return str(ipaddress.IPv6Address(new_int))
        return str(ipaddress.IPv4Address(new_int))

    @classmethod
    def from_string(
        cls,
        address: str,
        subnet: "Subnet",
        description: str | None = None,
        dns_name: str | None = None,
    ) -> "IPAddress":
        addr = ipaddress.ip_address(address)
        if addr not in subnet.network:
            raise ValueError(
                f"Address {address} is not within subnet {subnet.network_str}"
            )
        return cls(
            address=_int_to_hex(int(addr)),
            is_ipv6=isinstance(addr, ipaddress.IPv6Address),
            dns_name=dns_name,
            description=description,
            subnet_id=subnet.id,
        )
