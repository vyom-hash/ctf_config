import asyncio
import io
import os
import sys
from datetime import timedelta
from typing import Optional
from minio import Minio
from minio.error import S3Error
from app.core.config import settings
import logging

logger = logging.getLogger(__name__)


class MinioClientManager:
    """
    Manages MinIO client and bucket operations using environment-based configuration.
    """

    def __init__(self):
        self.client = Minio(
            f"{settings.MINIO_ENDPOINT}:{settings.MINIO_PORT}",
            access_key=settings.MINIO_ACCESS_KEY,
            secret_key=settings.MINIO_SECRET_KEY,
            secure=settings.MINIO_SECURE,
        )

    async def create_bucket(self, bucket_name: str) -> bool:
        """
        Creates a bucket if it doesn't exist.
        Returns True if bucket exists or was created, False on error.
        """
        try:
            loop = asyncio.get_running_loop()
            bucket_exists = await loop.run_in_executor(
                None, self.client.bucket_exists, bucket_name
            )
            if not bucket_exists:
                await loop.run_in_executor(
                    None, lambda: self.client.make_bucket(bucket_name=bucket_name)
                )
            return True
        except Exception as error:
            print(
                f"[MinIO][ERROR] create_bucket failed: {error} | "
                f"line: {sys.exc_info()[2].tb_lineno} | "
                f"file: {os.path.abspath(__file__)}"
            )
            return False

    async def ensure_bucket_exists(self, bucket_name: str) -> None:
        """
        Ensures the specified bucket exists in MinIO.
        """
        loop = asyncio.get_running_loop()
        exists = await loop.run_in_executor(
            None, self.client.bucket_exists, bucket_name
        )
        if not exists:
            await loop.run_in_executor(
                None, lambda: self.client.make_bucket(bucket_name)
            )

    def get_client(self) -> Minio:
        """
        Returns the MinIO client.
        """
        return self.client

    async def upload_file(
        self,
        bucket_name: str,
        file_data: bytes,
        file_name: str,
    ) -> Optional[str]:
        """
        Uploads bytes to MinIO and returns a presigned GET URL.
        Raises on upload failure so the caller's DB transaction can roll back.
        """
        if not file_data:
            print(f"[MinIO][WARN] No file data provided, skipping upload | bucket: {bucket_name} | file: {file_name}")
            return None

        try:
            loop = asyncio.get_running_loop()

            await loop.run_in_executor(
                None,
                lambda: self.client.put_object(
                    bucket_name=bucket_name,
                    object_name=file_name,
                    data=io.BytesIO(file_data),
                    length=len(file_data),
                    content_type="text/x-shellscript",
                ),
            )

            object_url = await loop.run_in_executor(
                None,
                lambda: self.client.get_presigned_url(
                    method="GET",
                    bucket_name=bucket_name,
                    object_name=file_name,
                ),
            )
            return object_url

        except Exception as error:
            print(
                f"[MinIO][ERROR] upload_file failed: {error} | "
                f"line: {sys.exc_info()[2].tb_lineno} | "
                f"file: {os.path.abspath(__file__)} | "
                f"bucket: {bucket_name} | file: {file_name}"
            )
            raise

    async def get_file_url(
        self,
        bucket_name: str,
        object_name: str,
        expiry: int = 3600,
    ) -> Optional[str]:
        """
        Generates a presigned URL for accessing an object.
        """
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: self.client.get_presigned_url(
                    method="GET",
                    bucket_name=bucket_name,
                    object_name=object_name,
                    expires=timedelta(seconds=expiry),
                ),
            )
        except Exception as error:
            print(
                f"[MinIO][ERROR] get_file_url failed: {error} | "
                f"line: {sys.exc_info()[2].tb_lineno} | "
                f"file: {os.path.abspath(__file__)}"
            )
            return None

    async def delete_file(self, bucket_name: str, object_name: str) -> bool:
        """
        Deletes a single file from MinIO.
        """
        try:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None,
                lambda: self.client.remove_object(bucket_name, object_name),
            )
            return True
        except Exception as error:
            print(
                f"[MinIO][ERROR] delete_file failed: {error} | "
                f"line: {sys.exc_info()[2].tb_lineno} | "
                f"file: {os.path.abspath(__file__)}"
            )
            return False

    def delete_bucket(self, bucket_name: str, force: bool = True) -> bool:
        """
        Deletes a bucket from MinIO, optionally force-deleting all objects first.
        """
        try:
            if force:
                objects = self.client.list_objects(bucket_name, recursive=True)
                for obj in objects:
                    self.client.remove_object(bucket_name, obj.object_name)
            self.client.remove_bucket(bucket_name)
            print(f"[MinIO][INFO] Bucket '{bucket_name}' deleted successfully")
            return True
        except Exception as error:
            print(
                f"[MinIO][ERROR] delete_bucket failed for '{bucket_name}': {error} | "
                f"line: {sys.exc_info()[2].tb_lineno} | "
                f"file: {os.path.abspath(__file__)}"
            )
            return False


minio_client = MinioClientManager()


# Script storage helpers — used by registry services

async def save_script_file(script_uuid: str, version: int, content: str) -> str:
    """
    Uploads script content to MinIO.

    Object path: <MINIO_SCRIPT_BUCKET>/<script_uuid>/<script_uuid>_<version>

    Returns the object path stored as `signature_reference` in RegistryRevision.
    Raises on failure so the caller's DB transaction rolls back cleanly.
    """
    bucket = settings.MINIO_SCRIPT_BUCKET
    object_name = f"{script_uuid}/{script_uuid}_{version}"

    await minio_client.ensure_bucket_exists(bucket)
    await minio_client.upload_file(
        bucket_name=bucket,
        file_data=content.encode("utf-8"),
        file_name=object_name,
    )
    return object_name


async def delete_script_files(script_uuid: str) -> None:
    """
    Deletes all MinIO objects under <script_uuid>/ prefix.
    Called after a successful DB delete — errors are logged but not raised.
    """
    bucket = settings.MINIO_SCRIPT_BUCKET
    client = await minio_client.get_client()

    try:
        loop = asyncio.get_running_loop()
        objects = await loop.run_in_executor(
            None,
            lambda: list(client.list_objects(bucket, prefix=f"{script_uuid}/", recursive=True)),
        )
        for obj in objects:
            await minio_client.delete_file(bucket, obj.object_name)
    except Exception as error:
        print(
            f"[MinIO][WARN] delete_script_files incomplete for {script_uuid}: {error} | "
            f"line: {sys.exc_info()[2].tb_lineno}"
        )

async def get_script_file(signature_reference: str) -> str:
    """
    Fetches script content from MinIO using the signature_reference
    stored on RegistryRevision (format: <script_uuid>/<script_uuid>_<version>).

    Returns decoded script content as a string.
    Raises on failure.
    """
    bucket = settings.MINIO_SCRIPT_BUCKET
    client = minio_client.get_client()             

    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None,
            lambda: client.get_object(bucket, signature_reference),
        )
        content = response.read().decode("utf-8")
        response.close()
        response.release_conn()
        return content
    except Exception as error:
        print(
            f"[MinIO][ERROR] get_script_file failed for '{signature_reference}': {error} | "
            f"line: {sys.exc_info()[2].tb_lineno} | "
            f"file: {os.path.abspath(__file__)}"
        )
        raise