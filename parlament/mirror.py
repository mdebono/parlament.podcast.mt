import json
import os
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from urllib.parse import unquote
from parlament import cache

R2_PARLAMENT_URL = 'https://r2.parlament.podcast.mt'

class ObjectNotFound(Exception):
    """Raised when a requested S3/R2 object does not exist."""

_s3_client = None

def _s3():
    global _s3_client
    if _s3_client is None:
        _s3_client = boto3.client(
            service_name="s3",
            config=Config(signature_version="s3v4"),
        )
    return _s3_client

def _bucket():
    bucket = os.environ.get("S3_BUCKET")
    if not bucket:
        raise RuntimeError("S3_BUCKET environment variable is not set")
    return bucket

def mirror_audio_to_r2(audio_url, s3_key):
    s3_key = prep_s3_key(s3_key)
    bucket = _bucket()

    # If the object already exists, skip downloading and uploading entirely.
    if s3_object_exists(s3_key):
        print(f"S3 object {s3_key} already exists in bucket '{bucket}'; skipping mirror.")
        return f"{R2_PARLAMENT_URL}/{s3_key}"

    # TODO: do not use temporary file; stream directly from source to S3
    local_file = "temp_audio.mp3"
    response = cache.httpGetFile(audio_url, local_file)
    response.raise_for_status()

    print(f"Uploading {s3_key} to bucket '{bucket}'")
    try:
        _s3().upload_file(local_file, bucket, s3_key)
    finally:
        os.remove(local_file)
    print(f"Uploaded {s3_key} to bucket '{bucket}' successfully")
    return f"{R2_PARLAMENT_URL}/{s3_key}"

def s3_object_exists(key):
    try:
        _s3().head_object(Bucket=_bucket(), Key=key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NotFound", "NoSuchKey"):
            return False
        raise
    return True

def prep_s3_key(audio_url):
    key = audio_url.lstrip('/')
    key = unquote(key)
    return key

def get_json(key):
    try:
        response = _s3().get_object(Bucket=_bucket(), Key=key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NotFound", "NoSuchKey"):
            raise ObjectNotFound(key) from e
        raise
    return json.loads(response['Body'].read())

def put_json(key, obj):
    body = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True).encode('utf8')
    _s3().put_object(Bucket=_bucket(), Key=key, Body=body,
                     ContentType='application/json')

def copy_object(src_key, dst_key):
    _s3().copy_object(Bucket=_bucket(), Key=dst_key,
                      CopySource={'Bucket': _bucket(), 'Key': src_key})

def get_r2_content_length(key):
    """Content-Length of an R2 object as a string, or '' if unavailable.
    R2 is authoritative for the enclosure actually served to clients."""
    try:
        response = _s3().head_object(Bucket=_bucket(), Key=key)
        return str(response['ContentLength'])
    except Exception as e:
        print(f'Warning: could not get content length for {key}: {e}')
        return ''
