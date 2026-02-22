from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import Depends, FastAPI

import auth
from auth import verify_api_key
from health import router as health_router
from subnets import router as subnets_router
from ip_addresses import router as ip_addresses_router
from dns_zones import router as dns_zones_router
from database import Base, engine
import models  # noqa: F401 - ensures tables are registered

Base.metadata.create_all(bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    load_dotenv()
    auth.load_keys()
    yield


app = FastAPI(lifespan=lifespan)
app.include_router(health_router)
app.include_router(subnets_router, dependencies=[Depends(verify_api_key)])
app.include_router(ip_addresses_router, dependencies=[Depends(verify_api_key)])
app.include_router(dns_zones_router, dependencies=[Depends(verify_api_key)])


@app.get("/")
async def root():
    return {"message": "Hello, World!"}
