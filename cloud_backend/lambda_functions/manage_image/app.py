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
    
    try:
        dynamodb = boto3.client('dynamodb')
        prefs_response = dynamodb.get_item(
            TableName='WoodsNetNotificationPrefs',
            Key={'ConfigKey': {'S': 'GLOBAL_PREFS'}}
        )
        if 'Item' in prefs_response:
            item = prefs_response['Item']
            if 'PortalPassword' in item:
                expected_token = item['PortalPassword']['S']
    except Exception as e:
        print(f"Error fetching portal config from DynamoDB: {e}")
    
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
    if action == 'bulk_delete' and not body.get('keys'):
        return {
            'statusCode': 400,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Missing required fields: keys'})
        }
        
    bucket_name = os.environ.get('UPLOAD_BUCKET_NAME')
    if not bucket_name:
        return {
            'statusCode': 500,
            'headers': cors_headers,
            'body': json.dumps({'error': 'Lambda configuration error: Missing UPLOAD_BUCKET_NAME environment variable.'})
        }

    # Ensure key is decoded properly in case the frontend sent an encoded URI
    if key:
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
            
        elif action == 'bulk_delete':
            keys = body.get('keys', [])
            if not isinstance(keys, list):
                return {
                    'statusCode': 400,
                    'headers': cors_headers,
                    'body': json.dumps({'error': 'Invalid format: keys must be a list'})
                }
            
            # Sanitize keys
            for k in keys:
                decoded_k = urllib.parse.unquote(k)
                if '..' in decoded_k:
                    return {
                        'statusCode': 400,
                        'headers': cors_headers,
                        'body': json.dumps({'error': 'Invalid key format: path traversal detected.'})
                    }
                    
            print(f"Bulk deleting {len(keys)} objects")
            
            # S3 delete_objects takes up to 1000 items at a time
            objects_to_delete = [{'Key': urllib.parse.unquote(k)} for k in keys]
            
            for i in range(0, len(objects_to_delete), 1000):
                chunk = objects_to_delete[i:i + 1000]
                s3_client.delete_objects(
                    Bucket=bucket_name,
                    Delete={
                        'Objects': chunk,
                        'Quiet': True
                    }
                )
                
            return {
                'statusCode': 200,
                'headers': cors_headers,
                'body': json.dumps({'message': f'Successfully deleted {len(keys)} objects'})
            }
            
        elif action == 'save_notification_prefs':
            prefs = body.get('prefs', {})
            try:
                dynamodb = boto3.client('dynamodb')
                dynamodb.update_item(
                    TableName='WoodsNetNotificationPrefs',
                    Key={'ConfigKey': {'S': 'GLOBAL_PREFS'}},
                    UpdateExpression='SET AlertOnPerson = :aop, AlertOnBuck = :aob',
                    ExpressionAttributeValues={
                        ':aop': {'BOOL': bool(prefs.get('alert_person', True))},
                        ':aob': {'BOOL': bool(prefs.get('alert_buck', True))}
                    }
                )
                return {
                    'statusCode': 200,
                    'headers': cors_headers,
                    'body': json.dumps({'message': 'Successfully saved notification preferences.'})
                }
            except Exception as e:
                print(f"Error saving to DynamoDB: {e}")
                return {
                    'statusCode': 500,
                    'headers': cors_headers,
                    'body': json.dumps({'error': 'Failed to save preferences to DynamoDB.'})
                }
                
        elif action == 'save_portal_config':
            portal_name = body.get('portal_name')
            portal_password = body.get('portal_password')
            if not portal_name or not portal_password:
                return {
                    'statusCode': 400,
                    'headers': cors_headers,
                    'body': json.dumps({'error': 'Missing required fields: portal_name or portal_password'})
                }
            
            try:
                dynamodb = boto3.client('dynamodb')
                dynamodb.update_item(
                    TableName='WoodsNetNotificationPrefs',
                    Key={'ConfigKey': {'S': 'GLOBAL_PREFS'}},
                    UpdateExpression='SET PortalName = :pn, PortalPassword = :pp',
                    ExpressionAttributeValues={
                        ':pn': {'S': portal_name},
                        ':pp': {'S': portal_password}
                    }
                )
                return {
                    'statusCode': 200,
                    'headers': cors_headers,
                    'body': json.dumps({'message': 'Successfully saved portal config.'})
                }
            except Exception as e:
                print(f"Error saving portal config to DynamoDB: {e}")
                return {
                    'statusCode': 500,
                    'headers': cors_headers,
                    'body': json.dumps({'error': 'Failed to save portal config to DynamoDB.'})
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
