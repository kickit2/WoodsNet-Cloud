import json
import boto3
import os
import urllib.parse

s3_client = boto3.client('s3')

def lambda_handler(event, context):
    """
    Handles image management operations: delete, rename.
    Requires MVP authentication via Authorization header.
    Expects a JSON body with 'action', 'key', and optionally 'new_key'.
    """
    headers = event.get('headers', {})
    # API Gateway lowercases headers
    auth_header = headers.get('authorization', '')
    
    expected_token = os.environ.get('PORTAL_PASSWORD', 'woods-net-demo')
    
    cors_headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'OPTIONS,POST',
        'Access-Control-Allow-Headers': 'Content-Type,Authorization',
        'Content-Type': 'application/json'
    }

    # Handle CORS preflight OPTIONS request if API Gateway doesn't catch it
    if event.get('httpMethod') == 'OPTIONS':
         return {
             'statusCode': 200,
             'headers': cors_headers,
             'body': ''
         }

    if auth_header != f"Bearer {expected_token}":
        return {
            'statusCode': 401,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Unauthorized: Invalid or missing password'})
        }
        
    try:
        body = json.loads(event.get('body', '{}'))
    except json.JSONDecodeError:
        return {
            'statusCode': 400,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Invalid JSON body'})
        }

    action = body.get('action')
    key = body.get('key')
    
    if not action:
        return {
            'statusCode': 400,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Missing required fields: action'})
        }
    if action in ['delete', 'rename'] and not key:
        return {
            'statusCode': 400,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Missing required fields: key'})
        }
        
    bucket_name = os.environ.get('UPLOAD_BUCKET_NAME')
    if not bucket_name:
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Lambda configuration error: Missing UPLOAD_BUCKET_NAME environment variable.'})
        }

    # Ensure key is decoded properly in case the frontend sent an encoded URI
    key = urllib.parse.unquote(key)
    
    # Basic Input Sanitization (Path Traversal Protection)
    if '..' in key:
        return {
            'statusCode': 400,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Invalid key format: path traversal detected.'})
        }

    try:
        if action == 'delete':
            print(f"Deleting object: {key}")
            s3_client.delete_object(Bucket=bucket_name, Key=key)
            return {
                'statusCode': 200,
                'headers': cors_headers,
                'body': json.dumps({'message': f'Successfully deleted {key}'})
            }
            
        elif action == 'rename':
            new_key = body.get('new_key')
            if not new_key:
                return {
                    'statusCode': 400,
                    'headers': cors_headers,
                    'body': json.dumps({'error': 'Missing required field for rename: new_key'})
                }
                
            new_key = urllib.parse.unquote(new_key)
            if '..' in new_key:
                return {
                    'statusCode': 400,
                    'headers': cors_headers,
                    'body': json.dumps({'error': 'Invalid new_key format: path traversal detected.'})
                }
            
            # Prevent renaming to a different folder structure if we want to enforce it, 
            # or just allow it. For now, we just copy.
            print(f"Renaming object from {key} to {new_key}")
            
            copy_source = {
                'Bucket': bucket_name,
                'Key': key
            }
            
            # S3 Rename is a Copy + Delete
            s3_client.copy_object(
                CopySource=copy_source,
                Bucket=bucket_name,
                Key=new_key
            )
            s3_client.delete_object(Bucket=bucket_name, Key=key)
            
            return {
                'statusCode': 200,
                'headers': cors_headers,
                'body': json.dumps({'message': f'Successfully renamed {key} to {new_key}'})
            }
            
        elif action == 'save_mappings':
            mappings = body.get('mappings', {})
            print(f"Saving mule mappings: {mappings}")
            s3_client.put_object(
                Bucket=bucket_name,
                Key='_config/mule_mappings.json',
                Body=json.dumps(mappings).encode('utf-8'),
                ContentType='application/json'
            )
            return {
                'statusCode': 200,
                'headers': cors_headers,
                'body': json.dumps({'message': 'Successfully saved mule mappings config.'})
            }
            
        else:
            return {
                'statusCode': 400,
                'headers': cors_headers,
                'body': json.dumps({'error': f'Unsupported action: {action}'})
            }
            
    except s3_client.exceptions.ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        print(f"S3 ClientError ({error_code}): {e}")
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': f'S3 Error: {error_code}'})
        }
    except Exception as e:
        print(f"Unexpected Error: {e}")
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Internal server error processing the request.'})
        }
