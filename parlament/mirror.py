import os
import boto3
from botocore.client import Config
from botocore.exceptions import ClientError
from urllib.parse import unquote
from parlament import cache

R2_PARLAMENT_URL = 'https://r2.parlament.podcast.mt'

S3_BUCKET = os.environ["S3_BUCKET"]

def mirror_audio_to_r2(audio_url, s3_key):
    s3 = boto3.client(
        service_name="s3",
        config=Config(signature_version="s3v4")
    )
    s3_key = prep_s3_key(s3_key)

    # If the object already exists, skip downloading and uploading entirely.
    if s3_object_exists(s3, s3_key):
        print(f"S3 object {s3_key} already exists in {S3_BUCKET}; skipping mirror.")
        return f"{R2_PARLAMENT_URL}/{s3_key}"

    # TODO: do not use temporary file; stream directly from source to S3
    local_file = "temp_audio.mp3"
    response = cache.httpGetFile(audio_url, local_file)
    response.raise_for_status()

    # TODO: log uploading
    s3.upload_file(local_file, S3_BUCKET, s3_key)
    # TODO: log uploaded successfully
    # os.remove(local_file)
    return f"{R2_PARLAMENT_URL}/{s3_key}"

def s3_object_exists(s3_client, key):
    try:
        s3_client.head_object(Bucket=S3_BUCKET, Key=key)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        if code in ("404", "NotFound", "NoSuchKey"):
            return False
    return True

def prep_s3_key(audio_url):
    key = audio_url.lstrip('/')
    key = unquote(key)
    return key