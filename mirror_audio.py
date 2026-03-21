from dotenv import load_dotenv
load_dotenv()

import os
import sys
import parlament.cache as cache
import boto3
from botocore.client import Config

S3_BUCKET = os.environ["S3_BUCKET"]

def download_audio(url, local_path):
    response = cache.httpGetFile(url, local_path)
    response.raise_for_status()

def upload_to_r2(local_path, r2_key):
    s3 = boto3.client(
        's3',
        config=Config(signature_version='s3v4')
    )
    s3.upload_file(local_path, S3_BUCKET, r2_key)

if __name__ == "__main__":
    import sys
    if len(sys.argv) != 3:
        print("Usage: python mirror_audio.py <audio_url> <r2_key>")
        sys.exit(1)
    audio_url = sys.argv[1]
    r2_key = sys.argv[2]
    local_file = "temp_audio.mp3"
    print(f"Downloading {audio_url}...")
    download_audio(audio_url, local_file)
    print(f"Uploading to R2 as {r2_key}...")
    upload_to_r2(local_file, r2_key)
    os.remove(local_file)
    print("Done.")
