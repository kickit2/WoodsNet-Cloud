import json
import os
import boto3
from botocore.exceptions import ClientError

def lambda_handler(event, context):
    """
    AWS Lambda handler to list images from the Woods-Net S3 bucket.
    Generates secure, temporary Presigned GET URLs for the frontend to render.
    Includes a basic hardcoded password check for MVP security.
    """
    try:
        portal_name = "Woods-Net"
        expected_token = os.environ.get('PORTAL_PASSWORD', 'woods-net-demo')
        notification_prefs = {'alert_person': True, 'alert_buck': True}
        
        try:
            dynamodb = boto3.client('dynamodb')
            prefs_response = dynamodb.get_item(
                TableName='WoodsNetNotificationPrefs',
                Key={'ConfigKey': {'S': 'GLOBAL_PREFS'}}
            )
            if 'Item' in prefs_response:
                item = prefs_response['Item']
                if 'PortalName' in item:
                    portal_name = item['PortalName']['S']
                if 'PortalPassword' in item:
                    expected_token = item['PortalPassword']['S']
                notification_prefs['alert_person'] = item.get('AlertOnPerson', {}).get('BOOL', True)
                notification_prefs['alert_buck'] = item.get('AlertOnBuck', {}).get('BOOL', True)
        except Exception as e:
            print(f"Error fetching portal config from DynamoDB: {e}")

        # Extract headers to check for our simple MVP password
        headers = event.get('headers', {})
        # API Gateway lowercases headers
        auth_header = headers.get('authorization', '')
        
        if auth_header != f"Bearer {expected_token}":
            return {
                'statusCode': 401,
                'headers': {
                    'Access-Control-Allow-Origin': '*',
                    'Content-Type': 'application/json'
                },
                'body': json.dumps({'error': 'Unauthorized: Invalid or missing password', 'portal_name': portal_name})
            }

        bucket_name = os.environ.get('UPLOAD_BUCKET_NAME')
        if not bucket_name:
            return {
                'statusCode': 500,
                'body': json.dumps({'error': 'Server misconfiguration: UPLOAD_BUCKET_NAME not set'})
            }

        s3_client = boto3.client('s3')
        images = []
        next_token = None
        mule_mappings = {}
        mule_status = {}
        
        # Fetch Mule Name Mappings
        try:
            mapping_obj = s3_client.get_object(Bucket=bucket_name, Key='_config/mule_mappings.json')
            mule_mappings = json.loads(mapping_obj['Body'].read().decode('utf-8'))
        except ClientError as e:
            if e.response['Error']['Code'] != 'NoSuchKey':
                print(f"Error fetching mappings config: {e}")
                
        # Fetch the list of objects with pagination
        query_params = event.get('queryStringParameters') or {}
        continuation_token = query_params.get('next_token')
        
        list_kwargs = {
            'Bucket': bucket_name,
            'Prefix': 'woods-net/mules/',
            'MaxKeys': 100
        }
        if continuation_token:
            list_kwargs['ContinuationToken'] = continuation_token
            
        response = s3_client.list_objects_v2(**list_kwargs)
        
        images = []
        if 'Contents' in response:
            # Collect keys for DynamoDB Batch Query
            keys_for_dynamo = [{'ImageKey': {'S': obj['Key']}} for obj in response['Contents'] if not obj['Key'].endswith('/')]
            
            ai_tags_map = {}
            if keys_for_dynamo:
                dynamodb = boto3.client('dynamodb')
                table_name = os.environ.get('DYNAMODB_TABLE_NAME', 'WoodsNetImageTags')
                
                # We limit S3 list to MaxKeys=100, which perfectly aligns with DynamoDB's 100 item BatchGetItem limit.
                try:
                    batch_response = dynamodb.batch_get_item(
                        RequestItems={
                            table_name: {
                                'Keys': keys_for_dynamo,
                                'AttributesToGet': ['ImageKey', 'HasAnimals', 'Tags', 'Weather', 'CaptureTime']
                            }
                        }
                    )
                    
                    for item in batch_response.get('Responses', {}).get(table_name, []):
                        img_key = item['ImageKey']['S']
                        has_animals = item.get('HasAnimals', {}).get('BOOL', False)
                        tags_raw = item.get('Tags', {}).get('M', {})
                        weather_raw = item.get('Weather', {}).get('M', {})
                        
                        # Convert DynamoDB 'M' containing 'N' (Strings) back to python integers
                        tags_parsed = {k: int(v['N']) for k, v in tags_raw.items() if 'N' in v}
                        weather_parsed = {k: float(v['N']) for k, v in weather_raw.items() if 'N' in v} if weather_raw else None
                        
                        capture_time = item.get('CaptureTime', {}).get('S')
                        
                        ai_tags_map[img_key] = {
                            'has_animals': has_animals,
                            'tags': tags_parsed,
                            'weather': weather_parsed,
                            'capture_time': capture_time
                        }
                except Exception as e:
                    print(f"Error fetching AI tags from DynamoDB: {e}")
                    
            # Fetch Mule Hardware States from DynamoDB
            unique_mules = list(set([obj['Key'].split('/')[2] for obj in response.get('Contents', []) if len(obj['Key'].split('/')) >= 3 and not obj['Key'].endswith('/')]))
            if unique_mules:
                dynamodb = boto3.client('dynamodb')
                table_name = os.environ.get('DYNAMODB_TABLE_NAME', 'WoodsNetImageTags')
                state_keys = [{'ImageKey': {'S': f"MULE_STATE#{mid}"}} for mid in unique_mules]
                
                # BatchGetItem supports up to 100 items, and we have ~few unique mules.
                try:
                    state_response = dynamodb.batch_get_item(
                        RequestItems={
                            table_name: {
                                'Keys': state_keys,
                                'AttributesToGet': ['ImageKey', 'LastHeartbeat', 'Battery', 'Signal', 'PowerLevel']
                            }
                        }
                    )
                    for item in state_response.get('Responses', {}).get(table_name, []):
                        m_id = item['ImageKey']['S'].split('#')[1]
                        mule_status[m_id] = {
                            'last_heartbeat': item.get('LastHeartbeat', {}).get('S'),
                            'battery': item.get('Battery', {}).get('N'),
                            'signal': item.get('Signal', {}).get('N'),
                            'power_level': item.get('PowerLevel', {}).get('S')
                        }
                except Exception as e:
                    print(f"Error fetching mule statuses: {e}")
                    
            # Sort by LastModified, newest first
            sorted_contents = sorted(response['Contents'], key=lambda obj: obj['LastModified'], reverse=True)
            
            for obj in sorted_contents:
                key = obj['Key']
                
                # Skip "directory" markers if any exist
                if key.endswith('/'): 
                    continue
                    
                # Extract metadata from the key (e.g. woods-net/mules/MULE05/IMG0004.avif)
                parts = key.split('/')
                mule_id = parts[2] if len(parts) >= 3 else "Unknown"
                filename = parts[-1]
                
                # Generate a short-lived URL (1 hour) so the browser can securely download the image
                presigned_url = s3_client.generate_presigned_url(
                    'get_object',
                    Params={
                        'Bucket': bucket_name,
                        'Key': key
                    },
                    ExpiresIn=3600 
                )
                
                # Use EXIF Capture Time if available, else fallback to S3 Upload Date
                ai_data = ai_tags_map.get(key, {'has_animals': False, 'tags': {}, 'weather': None, 'awaiting_id': True, 'capture_time': None})
                
                timestamp_str = ai_data.get('capture_time')
                if not timestamp_str:
                    timestamp_str = obj['LastModified'].replace(tzinfo=None).isoformat() + "Z"
                
                images.append({
                    'key': key,
                    'mule_id': mule_id,
                    'filename': filename,
                    'size_bytes': obj['Size'],
                    'timestamp': timestamp_str, 
                    'url': presigned_url,
                    'ai_data': ai_data
                })

        next_token = response.get('NextContinuationToken')

        # Notification Prefs are now fetched at the beginning along with the portal config.

        return {
            'statusCode': 200,
            'headers': {
                'Content-Type': 'application/json',
                # REQUIRED: Allow the browser frontend (which runs on a different domain) to call this API
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Headers': 'Authorization'
            },
            'body': json.dumps({'images': images, 'mule_mappings': mule_mappings, 'mule_status': mule_status, 'notification_prefs': notification_prefs, 'next_token': next_token, 'portal_name': portal_name})
        }

    except ClientError as e:
        print(f"Error accessing S3: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': 'Internal server error accessing storage'})
        }
    except Exception as e:
        print(f"Unexpected error: {e}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }
