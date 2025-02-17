import logging
import boto3
import json
import os
import uuid
import asyncio
from datetime import datetime
from dotenv import load_dotenv
from enum import Enum
from botocore.exceptions import ClientError
from asyncio import Lock
from fastapi import FastAPI, Request, HTTPException
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import set_span_in_context
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor


load_dotenv()

trace.set_tracer_provider(TracerProvider())
tracer = trace.get_tracer(__name__)

class LogLevel(Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"

class S3Logger:
    def __init__(self):
        self.bucket_name = os.getenv("S3_BUCKET_NAME")
        self.service_name = os.getenv("SERVICE_NAME", "default-service")
        self.s3_client = boto3.client(
            "s3",
            region_name=os.getenv("AWS_REGION"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY")
        )
        self.lock = Lock()
        self.loop = asyncio.get_event_loop()

    def log(self, message, level=LogLevel.INFO):
        span = trace.get_current_span()
        trace_id = format(span.get_span_context().trace_id, "032x") if span.get_span_context() else str(uuid.uuid4())
        self.loop.create_task(self._async_log(message, level, trace_id))

    async def _async_log(self, message, level, trace_id):
        async with self.lock:
            try:
                log_entry = {
                    "timestamp": datetime.utcnow().isoformat(),
                    "service": self.service_name,
                    "level": level.name,
                    "message": message,
                    "log_id": str(uuid.uuid4()),
                    "trace_id": trace_id
                }
                log_filename = f"logs/{self.service_name}/{level.name.lower()}/{datetime.utcnow().strftime('%Y-%m-%d')}.jsonl"

                try:
                    existing_logs = self.s3_client.get_object(Bucket=self.bucket_name, Key=log_filename)["Body"].read().decode("utf-8")
                except ClientError as e:
                    if e.response["Error"]["Code"] == "NoSuchKey":
                        existing_logs = ""  # No previous logs exist
                    else:
                        raise e  # Raise other errors
                print(log_entry)
                # Append new log entry
                updated_logs = existing_logs + json.dumps(log_entry) + "\n"

                # Upload updated log file to S3 asynchronously
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, lambda: self.s3_client.put_object(
                    Bucket=self.bucket_name,
                    Key=log_filename,
                    Body=updated_logs.encode("utf-8"),
                    ContentType="application/json",
                    ACL="private"
                ))
            except Exception as e:
                print(f"Error writing log to S3: {e}")