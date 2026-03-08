import os
import time
import requests
import threading

# Using an explicit log method to allow easy piping alongside Base Station stdout
def _log(msg):
    print(f"[CLOUD UPLOADER] {msg}", flush=True)

class CloudUploader:
    """
    Handles fetching S3 Presigned URLs from the AWS API Gateway
    and executing direct binary PUT uploads for completed Woods-Net files.
    """
    def __init__(self, api_url):
        self.api_url = api_url

    def upload_file_async(self, file_path, filename, mule_id):
        """
        Dispatches the upload process to a background thread to prevent
        blocking the single-threaded PyXBee radio ingestion loop.
        """
        if not self.api_url:
            _log("Skipping upload: AWS_API_URL not configured.")
            return

        thread = threading.Thread(
            target=self._execute_upload,
            args=(file_path, filename, mule_id),
            daemon=True
        )
        thread.start()
        _log(f"Spawned background upload thread for {filename}")

    def _execute_upload(self, file_path, filename, mule_id):
        """
        The blocking logic to fetch the URL and push to S3.
        Includes a basic 3-attempt retry loop for network resilience.
        """
        max_retries = 3
        
        if not os.path.exists(file_path):
             _log(f"ERROR: File {file_path} does not exist. Cannot upload.")
             return

        for attempt in range(1, max_retries + 1):
            try:
                # 1. Request the Presigned URL
                _log(f"Attempt {attempt}/{max_retries}: Requesting S3 URL for {filename}...")
                response = requests.get(
                    self.api_url, 
                    params={'filename': filename, 'mule_id': mule_id},
                    timeout=10 # Fail fast to retry
                )
                
                if response.status_code != 200:
                    _log(f"Failed to get URL (HTTP {response.status_code}): {response.text}")
                    time.sleep(2)
                    continue
                    
                data = response.json()
                upload_url = data.get('upload_url')
                s3_key = data.get('key')
                
                if not upload_url:
                     _log(f"Malformed response from API: {data}")
                     time.sleep(2)
                     continue

                # 2. Upload the Binary Payload direct to S3
                _log(f"Uploading {os.path.getsize(file_path)} bytes directly to S3...")
                
                with open(file_path, 'rb') as f:
                    # Essential: AWS requires the exact header specified during presigning
                    s3_response = requests.put(
                        upload_url, 
                        data=f, 
                        headers={'Content-Type': 'image/avif'},
                        timeout=30 # Larger files need more time
                    )
                    
                if s3_response.status_code == 200:
                    _log(f"SUCCESS! {filename} securely stored at {s3_key}")
                    
                    # Optional: Clean up the local file if we don't want to keep it on the Pi 4
                    # os.remove(file_path)
                    return # Exit the retry loop entirely
                else:
                    _log(f"Upload failed (HTTP {s3_response.status_code}): {s3_response.text}")

            except requests.exceptions.RequestException as e:
                _log(f"Network error during upload attempt {attempt}: {e}")
                
            time.sleep(2 ** attempt) # Exponential backoff
            
        _log(f"FATAL: Max retries ({max_retries}) exceeded for {filename}. Upload completely failed.")
