import json
import os
import boto3
from botocore.exceptions import ClientError

def lambda_handler(event, context):
    """
    AWS Lambda handler to generate an S3 Presigned URL for direct file uploads.
    Triggered via an API Gateway HTTP GET proxy integration.
    """
    try:
        # Extract query parameters (API Gateway HTTP API format)
        query_params = event.get('queryStringParameters', {})
        if not query_params:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing query parameters'})
            }

        filename = query_params.get('filename')
        mule_id = query_params.get('mule_id', 'unknown_mule')
        
        if not filename:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': 'Missing required parameter: filename'})
            }
            
        # Get the target bucket name from environment variables (injected by IaC)
        bucket_name = os.environ.get('UPLOAD_BUCKET_NAME')
        if not bucket_name:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Server misconfiguration: UPLOAD_BUCKET_NAME not set'})
            }

        # Construct the object key (path in the bucket)
        # e.g., woods-net/mules/MULE05/IMG0004_SZ451234.avif
        object_key = f"woods-net/mules/{mule_id}/{filename}"

        # Initialize S3 client
        # Note: boto3 automatically uses the Lambda execution role's credentials
        s3_client = boto3.client('s3')

        # Generate the presigned URL for a PUT request
        # 300 seconds (5 minutes) is plenty of time for the Base Station to initiate the upload
        presigned_url = s3_client.generate_presigned_url(
            'put_object',
            Params={
                'Bucket': bucket_name,
                'Key': object_key,
                'ContentType': 'image/avif' # Force AVIF content type for browser rendering
            },
            ExpiresIn=300 
        )

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                'Access-Control-Allow-Origin': '*' # Allow requests if we ever build a web UI
            },
            'body': json.dumps({
                'upload_url': presigned_url,
                'key': object_key,
                'expires_in': 300
            })
        }

    except ClientError as e:
        print(f"Error generating presigned URL: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error generating URL'})
        }
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
