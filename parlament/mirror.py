import os
import boto3
from botocore.client import Config
from parlament import cache
from parlament.papi import R2_PARLAMENT_URL

S3_BUCKET = os.environ["S3_BUCKET"]

def mirror_audio_to_r2(audio_url, s3_key):
    local_file = "temp_audio.mp3"
    response = cache.httpGetFile(audio_url, local_file)
    response.raise_for_status()
    s3 = boto3.client(
        service_name="s3",
        config=Config(signature_version="s3v4")
    )
    s3_key = s3_key.lstrip('/')
    print(s3_key)
    s3.upload_file(local_file, S3_BUCKET, s3_key)
    # os.remove(local_file)
    return f"{R2_PARLAMENT_URL}/{s3_key}"
