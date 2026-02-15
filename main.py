from fastapi import FastAPI
from health import router as health_router
from subnets import router as subnets_router
from ip_addresses import router as ip_addresses_router
from dns_zones import router as dns_zones_router
from database import Base, engine
import models  # noqa: F401 - ensures tables are registered

Base.metadata.create_all(bind=engine)

app = FastAPI()
app.include_router(health_router)
app.include_router(subnets_router)
app.include_router(ip_addresses_router)
app.include_router(dns_zones_router)


@app.get("/")
async def root():
    return {"message": "Hello, World!"}
