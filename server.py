from fastapi import FastAPI, HTTPException, Request, Depends
from loguru import logger
from opentelemetry.sdk.trace.sampling import StaticSampler
from pydantic import BaseModel
from typing import Optional, List
from prometheus_fastapi_instrumentator import Instrumentator
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.orm import sessionmaker, Session, declarative_base
from databases import Database
import sys
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
import json

# OpenTelemetry Imports
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.jaeger.thrift import JaegerExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

service_name = "fastapi-app"

# FastAPI Application
app = FastAPI()

# Prometheus Metrics (Ensure Exclusion from Tracing)
instrumentator = Instrumentator().instrument(app)
instrumentator.expose(app, endpoint="/metrics")

# OpenTelemetry Instrumentation (Exclude `/metrics`)
FastAPIInstrumentor.instrument_app(app, excluded_urls=r".*metrics.*")
RequestsInstrumentor().instrument(excluded_urls=r".*metrics.*")

trace.set_tracer_provider(
    TracerProvider(
        resource=Resource.create({"service.name": service_name}),  # <-- Set Service Name
    )
)
tracer = trace.get_tracer(service_name)

# Use HTTP instead of UDP
jaeger_exporter = JaegerExporter(
    collector_endpoint="http://localhost:14268/api/traces",  # Use HTTP endpoint instead of UDP
)

trace.get_tracer_provider().add_span_processor(BatchSpanProcessor(jaeger_exporter))


def get_trace_id():
    span = trace.get_current_span()
    if not span or not span.get_span_context():
        return None
    return format(span.get_span_context().trace_id, "032x")

def serialize(record):
    subset = {
        "timestamp": record["time"].strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "message": record["message"],
        "level": record["level"].name,
        "filename": record["file"].name,
        "traceId": get_trace_id(),
        "service_name": "fastapi-app"
    }
    return json.dumps(subset)


def patching(record):
    record["extra"]["serialized"] = serialize(record)

# Logging Configuration
log_file = "/var/log/fastapi.log"
logger.remove()  # Remove default log handlers
logger = logger.patch(patching)
logger.add(sys.stdout, format="{extra[serialized]}", level="INFO")  # Console output
logger.add(log_file, format="{extra[serialized]}", level="INFO", rotation="10 MB")  # File output

# Database Configuration
DATABASE_URL = "mysql+pymysql://:@localhost:3306/testdb"

# SQLAlchemy Database Setup
database = Database(DATABASE_URL)
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Define SQLAlchemy Model
class Item(Base):
    __tablename__ = "items"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    description = Column(String(255), nullable=True)

# Create Table if it doesn't exist
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

# Pydantic Schema
class ItemCreate(BaseModel):
    name: str
    description: Optional[str] = None

class ItemResponse(BaseModel):
    id: int
    name: str
    description: Optional[str] = None

    @classmethod
    def from_orm(cls, obj):
        return cls(id=obj.id, name=obj.name, description=obj.description)

# ------------------ Middleware ------------------
@app.middleware("http")
async def log_requests_middleware(request: Request, call_next):
    # Skip tracing and logging for /metrics
    if request.url.path == "/metrics":
        print("Here!")
        response = await call_next(request)
        return response  # No tracing, no logging

    # Create span only for non-metrics requests
    with tracer.start_as_current_span(f"HTTP {request.method} {request.url.path}") as span:
        response = None
        try:
            trace_id = format(span.get_span_context().trace_id, "032x")
            logger.bind(trace_id=trace_id)  # Attach trace ID to logs

            logger.info(f"Incoming request: {request.method} {request.url}")
            response = await call_next(request)
            logger.info(f"Response sent: {response.status_code}")

            return response
        except Exception as e:
            logger.error(str(e))
            raise e

# ------------------ CRUD Operations ------------------

# Create an Item (POST)
@app.post("/items/", response_model=ItemResponse)
def create_item(item: ItemCreate, db: Session = Depends(get_db)):
    db_item = Item(name=item.name, description=item.description)
    db.add(db_item)
    db.commit()
    db.refresh(db_item)
    logger.info(f"Item created: {db_item}")
    return ItemResponse.from_orm(db_item)  # Convert to Pydantic model

# Get All Items (GET)
@app.get("/items/", response_model=List[ItemResponse])
def read_items(db: Session = Depends(get_db)):
    items = db.query(Item).all()
    logger.info(f"Retrieved {len(items)} items")
    return [ItemResponse.from_orm(item) for item in items]  # Convert each item

# Get Single Item by ID (GET)
@app.get("/items/{item_id}", response_model=ItemResponse)
def read_item(item_id: int, db: Session = Depends(get_db)):
    item = db.query(Item).filter(Item.id == item_id).first()
    if not item:
        logger.warning(f"Item with ID {item_id} not found")
        raise HTTPException(status_code=404, detail="Item not found")
    return ItemResponse.from_orm(item)

# Update an Item (PUT)
@app.put("/items/{item_id}", response_model=ItemResponse)
def update_item(item_id: int, item: ItemCreate, db: Session = Depends(get_db)):
    db_item = db.query(Item).filter(Item.id == item_id).first()
    if not db_item:
        logger.warning(f"Item with ID {item_id} not found for update")
        raise HTTPException(status_code=404, detail="Item not found")

    db_item.name = item.name
    db_item.description = item.description
    db.commit()
    db.refresh(db_item)
    logger.info(f"Item updated: {db_item}")
    return ItemResponse.from_orm(db_item)

# Delete an Item (DELETE)
@app.delete("/items/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    db_item = db.query(Item).filter(Item.id == item_id).first()
    if not db_item:
        logger.warning(f"Item with ID {item_id} not found for deletion")
        raise HTTPException(status_code=404, detail="Item not found")

    db.delete(db_item)
    db.commit()
    logger.info(f"Item deleted: ID {item_id}")
    return {"message": "Item deleted successfully"}

# ------------------ Default Routes ------------------

class LogRequest(BaseModel):
    message: str
    error: Optional[str] = ""

@app.post("/hello")
def log_message(request: LogRequest):
    logger.info(f"Message: {request.message}")
    if request.error:
        logger.error(f"Error: {request.error}")
    return {"status": "success", "message": "Hello world!!"}

@app.get("/")
def root():
    logger.info("Root endpoint accessed")
    return {"message": "FastAPI logging with Grafana Alloy"}

# ------------------ Start FastAPI ------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)