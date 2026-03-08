import json
import boto3
import os
import subprocess
import tempfile
import urllib.parse
from datetime import datetime

s3_client = boto3.client('s3')

def lambda_handler(event, context):
    """
    Handles request to generate a timelapse video for a specific Mule ID.
    Expected JSON Body:
    {
        "mule_id": "MULE05",
        "fps": 5
    }
    """
    headers = event.get('headers', {})
    auth_header = headers.get('authorization', '')
    expected_token = os.environ.get('PORTAL_PASSWORD', 'woods-net-demo')
    
    cors_headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'OPTIONS,POST',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Content-Type': 'application/json'
    }

    if event.get('httpMethod') == 'OPTIONS':
         return {'statusCode': 200, 'headers': cors_headers, 'body': ''}

    if auth_header != f"Bearer {expected_token}":
        return {'statusCode': 401, 'headers': cors_headers, 'body': json.dumps({'error': 'Unauthorized'})}
        
    try:
        body = json.loads(event.get('body', '{}'))
    except json.JSONDecodeError:
        return {'statusCode': 400, 'headers': cors_headers, 'body': json.dumps({'error': 'Invalid JSON'})}

    mule_id = body.get('mule_id')
    fps = body.get('fps', 5)
    
    if not mule_id:
        return {'statusCode': 400, 'headers': cors_headers, 'body': json.dumps({'error': 'Missing mule_id'})}

    bucket_name = os.environ.get('UPLOAD_BUCKET_NAME')
    prefix = f"woods-net/mules/{mule_id}/"

    try:
        # Fetch list of images for this mule
        response = s3_client.list_objects_v2(Bucket=bucket_name, Prefix=prefix)
        if 'Contents' not in response or len(response['Contents']) < 2:
            return {'statusCode': 400, 'headers': cors_headers, 'body': json.dumps({'error': 'Not enough images to create a timelapse'})}

        # Sort by oldest first for timeline order
        objects = sorted([obj for obj in response['Contents'] if not obj['Key'].endswith('/')], key=lambda x: x['LastModified'])
        
        # Limit to last 100 images for Lambda processing constraints (timeout, space)
        objects = objects[-100:] 
        
        with tempfile.TemporaryDirectory() as temp_dir:
            file_list_path = os.path.join(temp_dir, 'input.txt')
            with open(file_list_path, 'w') as f:
                for idx, obj in enumerate(objects):
                    key = obj['Key']
                    local_path = os.path.join(temp_dir, f"img_{idx:04d}.avif")
                    
                    # Download image
                    s3_client.download_file(bucket_name, key, local_path)
                    
                    # Add to ffmpeg concat list
                    f.write(f"file '{local_path}'\n")

            out_filename = f"timelapse_{mule_id}_{int(datetime.now().timestamp())}.mp4"
            out_path = os.path.join(temp_dir, out_filename)
            
            # Execute ffmpeg. Expecting a static build bundled or layered
            # Using basic AVIF -> MP4 conversion. Note: Some older ffmpeg builds lack avif support.
            try:
                ffmpeg_cmd = [
                    'ffmpeg', '-y', 
                    '-r', str(fps), 
                    '-f', 'concat', 
                    '-safe', '0', 
                    '-i', file_list_path,
                    '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p',
                    out_path
                ]
                subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            except FileNotFoundError:
                # Mock response if ffmpeg is missing in local dev/test
                return {'statusCode': 500, 'headers': cors_headers, 'body': json.dumps({'error': 'ffmpeg executable not found in Lambda environment. A Layer is required.'})}
            except subprocess.CalledProcessError as e:
                return {'statusCode': 500, 'headers': cors_headers, 'body': json.dumps({'error': f'ffmpeg failed: {e.stderr.decode()}'})}

            # Upload the finished MP4
            s3_key = f"woods-net/timelapses/{mule_id}/{out_filename}"
            s3_client.upload_file(out_path, bucket_name, s3_key, ExtraArgs={'ContentType': 'video/mp4'})
            
            # Generate a presigned URL to download it directly
            download_url = s3_client.generate_presigned_url(
                'get_object',
                Params={'Bucket': bucket_name, 'Key': s3_key},
                ExpiresIn=3600
            )

        return {
            'statusCode': 200,
            'headers': cors_headers,
            'body': json.dumps({
                'message': 'Timelapse generated successfully.',
                'url': download_url,
                'filename': out_filename,
                'frames': len(objects)
            })
        }

    except Exception as e:
        print(f"Error: {e}")
        return {'statusCode': 500, 'headers': cors_headers, 'body': json.dumps({'error': str(e)})}
