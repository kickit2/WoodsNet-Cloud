import os
import glob
import boto3

BUCKET_NAME = "woods-net-storage"
REGION = "us-east-1"
TARGET_DIR = "/home/kickit2/gemini/antigravity/scratch/deer_pics"

def stealth_upload():
    print(f"[*] Initiating Stealth Drop into {BUCKET_NAME}...")
    s3_client = boto3.client('s3', region_name=REGION)
    
    # 1. Capture existing notification config
    current_config = {}
    try:
        current_config = s3_client.get_bucket_notification_configuration(Bucket=BUCKET_NAME)
        # Boto3 get_bucket_notification_configuration returns ResponseMetadata which fails on put
        current_config.pop('ResponseMetadata', None)
        print("[+] Captured existing S3 EventBridge Configuration.")
    except Exception as e:
        print(f"[-] No existing config or error: {e}")

    # 2. Blackout: Wipe the configuration
    print("[!] Severing S3 Lambda Triggers...")
    s3_client.put_bucket_notification_configuration(
        Bucket=BUCKET_NAME,
        NotificationConfiguration={}
    )
    print("    -> AI Trigger is now BLIND.")

    # 3. Payload Drop
    avif_files = glob.glob(os.path.join(TARGET_DIR, "*.AVIF"))
    print(f"[*] Uploading {len(avif_files)} telemetry assets...")
    
    for count, file_path in enumerate(avif_files, start=1):
        filename = os.path.basename(file_path)
        s3_key = f"woods-net/mules/{filename}"
        
        s3_client.upload_file(file_path, BUCKET_NAME, s3_key)
        print(f"  -> [{count}/{len(avif_files)}] Uploaded {filename} to {s3_key}")
        
    print("[+] All assets injected as S3 Orphans.")

    # 4. Re-establish Connection
    print("[!] Reinstating S3 Lambda Triggers...")
    if current_config:
        s3_client.put_bucket_notification_configuration(
            Bucket=BUCKET_NAME,
            NotificationConfiguration=current_config
        )
        print("    -> AI Trigger is back ONLINE.")
    else:
        print("    -> No original config to restore.")

    print("\n[SUCCESS] Stealth Drop Complete. The assets are locked as Orphans awaiting the Force Sweep.")

if __name__ == "__main__":
    stealth_upload()
